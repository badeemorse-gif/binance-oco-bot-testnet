@echo off
REM ============================================================================
REM G1.30 chunk_5 — تشغيل واجهة OCOBot مع تسليح شبكة أمان المركز على Testnet.
REM الاستخدام (من جذر المشروع D:\oco):
REM     tools\run_guardian_testnet.bat            ^<- observe (الافتراضي، بلا وضع فعلي)
REM     tools\run_guardian_testnet.bat observe
REM     tools\run_guardian_testnet.bat live       ^<- يضع وقفًا حمائيًّا فعليًّا على Testnet
REM ملاحظة: البيئة مقفولة على Testnet داخل app.main() ولا يمكن أن تنزلق إلى live-funds.
REM ============================================================================
setlocal
set "MODE=%~1"
if "%MODE%"=="" set "MODE=observe"
set "OCOBOT_GUARDIAN=%MODE%"
echo [guardian] OCOBOT_GUARDIAN=%OCOBOT_GUARDIAN%  (Testnet)
python -m ocobot.ui.app
endlocal
