#!/bin/sh
# Fixed macOS SSH_ASKPASS boundary for the T4-K controller signing ceremony.
# It deliberately never logs, caches, repeats, or places a passphrase in an
# argv.  Only OpenSSH's two expected prompt families reach a GUI dialog.

set -f
umask 077

if [ "$#" -ne 1 ]; then
    exit 64
fi

prompt=$1
passphrase_prefix='Enter passphrase for /Users/'
retry_prefix='Bad passphrase, try again for /Users/'
key_suffix='/Library/Application Support/AI小说世界2026/controller-authority/controller_ed25519: '

case "$prompt" in
    "$passphrase_prefix"*"$key_suffix"|"$retry_prefix"*"$key_suffix")
        case "$prompt" in
            "$passphrase_prefix"*) account=${prompt#"$passphrase_prefix"} ;;
            *) account=${prompt#"$retry_prefix"} ;;
        esac
        account=${account%"$key_suffix"}
        case "$account" in
            ''|*/*|*'
'*) exit 65 ;;
        esac
        exec /usr/bin/osascript <<'APPLESCRIPT'
set answerDialog to display dialog "请输入 T4-K Controller 签名密钥的口令。口令仅返回给本次 ssh-add，不会保存。" default answer "" with hidden answer buttons {"取消", "继续"} default button "继续" cancel button "取消" with title "AI小说世界2026 · Controller 签名"
return text returned of answerDialog
APPLESCRIPT
        ;;
esac

newline='
'
confirm_prefix='Allow use of key '
fingerprint_marker="?${newline}Key fingerprint SHA256:"

case "$prompt" in
    "$confirm_prefix"*"$fingerprint_marker"???????????????????????????????????????????'.')
        key_description=${prompt#"$confirm_prefix"}
        key_description=${key_description%%"$fingerprint_marker"*}
        case "$key_description" in
            ''|*'
'*) exit 66 ;;
        esac
        exec /usr/bin/osascript <<'APPLESCRIPT'
set confirmDialog to display dialog "是否允许固定 T4-K Controller 密钥执行这一次签名？拒绝是安全默认。" buttons {"拒绝", "允许"} default button "拒绝" with title "AI小说世界2026 · 单次签名确认" with icon caution
if button returned of confirmDialog is "允许" then
    return "yes"
end if
return "no"
APPLESCRIPT
        ;;
esac

exit 67
