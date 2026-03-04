; OpenAkita Setup Center - NSIS Hooks
; 目标：
; - 卸载时强制杀掉残留进程（Setup Center 本体 + OpenAkita 后台服务）
; - 勾选"清理用户数据"时，删除用户目录下的 ~/.openakita

; ── PATH 辅助脚本 ──
; 通过 PowerShell 安全地读写 PATH 注册表值，解决：
; 1. NSIS ReadRegStr 字符串长度上限导致长 PATH 被截断/清空
; 2. 保持 REG_EXPAND_SZ 类型（保留 %USERPROFILE% 等环境变量引用）
; 3. 使用分号分割后逐条精确比较，避免子字符串误匹配
!macro _OpenAkita_WritePathHelper
  InitPluginsDir
  FileOpen $R9 "$PLUGINSDIR\_oa_pathhelper.ps1" w
  FileWrite $R9 "param([string]$$Action, [string]$$BinDir, [string]$$RegPath)$\r$\n"
  FileWrite $R9 "$$ErrorActionPreference = 'Stop'$\r$\n"
  FileWrite $R9 "try {$\r$\n"
  FileWrite $R9 "    $$key = Get-Item -LiteralPath $$RegPath -ErrorAction SilentlyContinue$\r$\n"
  FileWrite $R9 "    if (-not $$key) {$\r$\n"
  FileWrite $R9 "        if ($$Action -eq 'add') {$\r$\n"
  FileWrite $R9 "            New-Item -Path $$RegPath -Force | Out-Null$\r$\n"
  FileWrite $R9 "            New-ItemProperty -Path $$RegPath -Name 'Path' -Value $$BinDir -PropertyType ExpandString | Out-Null$\r$\n"
  FileWrite $R9 "        }$\r$\n"
  FileWrite $R9 "        exit 0$\r$\n"
  FileWrite $R9 "    }$\r$\n"
  FileWrite $R9 "    $$cur = $$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')$\r$\n"
  FileWrite $R9 "    $$bn = $$BinDir.TrimEnd([char]92)$\r$\n"
  FileWrite $R9 "    if ($$Action -eq 'add') {$\r$\n"
  FileWrite $R9 "        if (-not $$cur) {$\r$\n"
  FileWrite $R9 "            Set-ItemProperty -LiteralPath $$RegPath -Name 'Path' -Value $$BinDir -Type ExpandString$\r$\n"
  FileWrite $R9 "        } else {$\r$\n"
  FileWrite $R9 "            $$entries = $$cur -split ';'$\r$\n"
  FileWrite $R9 "            $$found = $$entries | Where-Object { $$_.TrimEnd([char]92) -ieq $$bn }$\r$\n"
  FileWrite $R9 "            if (-not $$found) {$\r$\n"
  FileWrite $R9 '                $$np = "$$cur;$$BinDir"$\r$\n'
  FileWrite $R9 "                Set-ItemProperty -LiteralPath $$RegPath -Name 'Path' -Value $$np -Type ExpandString$\r$\n"
  FileWrite $R9 "            }$\r$\n"
  FileWrite $R9 "        }$\r$\n"
  FileWrite $R9 "    } elseif ($$Action -eq 'remove') {$\r$\n"
  FileWrite $R9 "        if ($$cur) {$\r$\n"
  FileWrite $R9 "            $$filtered = ($$cur -split ';') | Where-Object { $$_ -and ($$_.TrimEnd([char]92) -ine $$bn) }$\r$\n"
  FileWrite $R9 "            $$np = $$filtered -join ';'$\r$\n"
  FileWrite $R9 "            if ($$np -cne $$cur) {$\r$\n"
  FileWrite $R9 "                Set-ItemProperty -LiteralPath $$RegPath -Name 'Path' -Value $$np -Type ExpandString$\r$\n"
  FileWrite $R9 "            }$\r$\n"
  FileWrite $R9 "        }$\r$\n"
  FileWrite $R9 "    }$\r$\n"
  FileWrite $R9 "    exit 0$\r$\n"
  FileWrite $R9 "} catch {$\r$\n"
  FileWrite $R9 "    exit 1$\r$\n"
  FileWrite $R9 "}$\r$\n"
  FileClose $R9
!macroend

!macro _OpenAkita_KillPid pid
  StrCpy $0 "${pid}"
  ; 仅在 pid 非空时执行 kill；优先 PowerShell 不弹窗，失败则兜底 taskkill（会闪黑框）
  ${If} $0 != ""
    ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "Stop-Process -Id $0 -Force -ErrorAction SilentlyContinue"' $1
    ${If} $1 != 0
      ExecWait 'taskkill /PID $0 /T /F' $1
    ${EndIf}
  ${EndIf}
!macroend

!macro _OpenAkita_KillAllServicePids
  ; ~/.openakita/run/openakita-*.pid
  ; 先构建基础目录路径，再拼接通配符
  ExpandEnvStrings $R7 "%USERPROFILE%\\.openakita\\run"
  FindFirst $R1 $R2 "$R7\\openakita-*.pid"
  ${DoWhile} $R2 != ""
    ; 读 pid 文件（$R2 是文件名，$R7 是目录，拼接完整路径）
    FileOpen $R4 "$R7\\$R2" "r"
    ${IfNot} ${Errors}
      FileRead $R4 $R5
      FileClose $R4
      ; $R5 可能带 \r\n，截取前 32 字符
      StrCpy $R6 $R5 32
      ; kill
      !insertmacro _OpenAkita_KillPid $R6
    ${EndIf}
    ; next
    FindNext $R1 $R2
  ${Loop}
  FindClose $R1
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; 安装前（Section Install 入口处）：强制杀掉所有旧进程，防止文件锁定导致覆盖失败
  ; 即使 PageLeaveEnvCheck 中已执行过，这里再次确保（覆盖进程可能在页面间重启）

  ; 1) 杀掉 Setup Center（托盘常驻）
  ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "Get-Process -Name openakita-setup-center -ErrorAction SilentlyContinue | Stop-Process -Force"' $0
  ${If} $0 != 0
    ExecWait 'taskkill /IM openakita-setup-center.exe /T /F' $0
  ${EndIf}

  ; 2) 杀掉 openakita-server（PyInstaller 打包的后端）
  ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "Get-Process -Name openakita-server -ErrorAction SilentlyContinue | Stop-Process -Force"' $0
  ${If} $0 != 0
    ExecWait 'taskkill /IM openakita-server.exe /T /F' $0
  ${EndIf}

  ; 3) 杀掉 PID 文件追踪的服务进程（python 方式启动的后端）
  !insertmacro _OpenAkita_KillAllServicePids

  ; 4) 等待进程完全退出释放文件锁
  Sleep 2000
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; 卸载前：强制杀掉残留进程；优先 PowerShell 不弹窗，失败则兜底 taskkill（会闪黑框）
  ; 1) 杀掉 Setup Center（可能在托盘常驻）
  ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "Get-Process -Name openakita-setup-center -ErrorAction SilentlyContinue | Stop-Process -Force"' $0
  ${If} $0 != 0
    ExecWait 'taskkill /IM openakita-setup-center.exe /T /F' $0
  ${EndIf}

  ; 2) 杀掉 openakita-server（PyInstaller 打包的后端）
  ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "Get-Process -Name openakita-server -ErrorAction SilentlyContinue | Stop-Process -Force"' $0
  ${If} $0 != 0
    ExecWait 'taskkill /IM openakita-server.exe /T /F' $0
  ${EndIf}

  ; 3) 杀掉 PID 文件追踪的服务进程
  !insertmacro _OpenAkita_KillAllServicePids

  Sleep 2000
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; 安装完成后：写入版本信息到 state.json（供 App 环境检测用）
  ; 注意：state.json 可能已存在（升级安装），仅更新版本字段
  ExpandEnvStrings $R0 "%USERPROFILE%\.openakita"
  CreateDirectory "$R0"

  ; 写入 cli.json（供 Rust get_cli_status 读取）
  ReadRegDWORD $R1 HKCU "Software\OpenAkita\CLI" "openakita"
  ReadRegDWORD $R2 HKCU "Software\OpenAkita\CLI" "oa"
  ReadRegDWORD $R3 HKCU "Software\OpenAkita\CLI" "addToPath"
  ; 构造 JSON 中的 commands 数组
  StrCpy $R4 ""
  ${If} $R1 = ${BST_CHECKED}
    StrCpy $R4 '"openakita"'
  ${EndIf}
  ${If} $R2 = ${BST_CHECKED}
    ${If} $R4 != ""
      StrCpy $R4 '$R4, "oa"'
    ${Else}
      StrCpy $R4 '"oa"'
    ${EndIf}
  ${EndIf}
  ; 写入 cli.json
  ${If} $R4 != ""
    FileOpen $R5 "$R0\cli.json" w
    FileWrite $R5 '{"commands": [$R4], "addToPath": '
    ${If} $R3 = ${BST_CHECKED}
      FileWrite $R5 'true'
    ${Else}
      FileWrite $R5 'false'
    ${EndIf}
    FileWrite $R5 ', "binDir": "$INSTDIR\bin", "installedAt": "${VERSION}"}'
    FileClose $R5
  ${EndIf}

  ; 以当前用户身份清理旧环境组件（安全网：处理 NSIS 进程上下文与实际用户不同的边界情况）
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" "--clean-env venv runtime"

  ; Finish 页面会提供"运行应用程序"选项 (带 --first-run 参数)
  ; 这里无需额外操作，RunMainBinary 已带 --first-run
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; 勾选"清理用户数据"时：删除 ~/.openakita；优先 PowerShell 不弹窗，失败则兜底 cmd（会闪黑框）
  ; 仅在非更新模式下清理（与默认行为保持一致）
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    ExpandEnvStrings $R0 "%USERPROFILE%\\.openakita"
    System::Call 'kernel32::SetEnvironmentVariable(t "NSIS_DEL_PATH", t R0)'
    ExecWait 'powershell -NoProfile -WindowStyle Hidden -Command "try { Remove-Item -LiteralPath $env:NSIS_DEL_PATH -Recurse -Force -ErrorAction Stop } catch { exit 1 }"' $0
    ${If} $0 != 0
      ExecWait 'cmd /c rd /s /q "$R0"'
    ${EndIf}
  ${EndIf}
!macroend
