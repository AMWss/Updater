#!/bin/sh
# Sheng iPad Agent v1.1 one-line installer for Dopamine Rootless.
# Run as mobile: curl -fsSL URL | sh
set -eu

printf '%s\n' '[Sheng Agent] iPad Rootless 安装器 v1.1'
if [ "$(id -u)" = '0' ]; then
  printf '%s\n' '错误：请在 NewTerm 中以 mobile 用户运行，不要使用 root/sudo。' >&2
  exit 1
fi
if [ ! -d /var/jb ]; then
  printf '%s\n' '提示：没有检测到 /var/jb。请确认 Dopamine Rootless 已激活。' >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  printf '%s\n' '错误：没有 curl。请先通过 Sileo 安装 curl。' >&2
  exit 1
fi

PY=''
if command -v python3 >/dev/null 2>&1; then
  PY=$(command -v python3)
elif [ -x /var/jb/usr/bin/python3 ]; then
  PY=/var/jb/usr/bin/python3
elif [ -x /var/jb/bin/python3 ]; then
  PY=/var/jb/bin/python3
fi
if [ -z "$PY" ]; then
  printf '%s\n' '错误：没有 Python 3。请先在 Sileo 安装 Procursus python3，然后重新运行本条 curl 命令。' >&2
  exit 1
fi
if ! "$PY" -c 'import sys; assert sys.version_info >= (3,8)' >/dev/null 2>&1; then
  printf '%s\n' '错误：需要 Python >= 3.8。' >&2
  exit 1
fi

SOURCE='https://raw.githubusercontent.com/AMWss/Updater/sheng-ipad-agent-v1/ipad-agent/agent.py'
# GitHub blob SHA1 of the audited agent.py. Prevents loading changed content.
EXPECTED='a4a1eba724f656a1a5bc7242176f922509c8be3d'
APP="$HOME/.local/share/sheng-ipad-agent"
BIN="$HOME/.local/bin"
mkdir -p "$APP" "$BIN"
umask 077
TMP=$(mktemp "$APP/.download.XXXXXX")
trap 'rm -f "$TMP"' EXIT HUP INT TERM

printf '%s\n' '[1/3] 正在下载代理程序...'
curl -fsSL --connect-timeout 15 --max-time 90 "$SOURCE" -o "$TMP"

printf '%s\n' '[2/3] 正在核对 GitHub Blob SHA...'
"$PY" - "$TMP" "$EXPECTED" <<'PYCODE'
import hashlib, pathlib, sys
content = pathlib.Path(sys.argv[1]).read_bytes()
blob = b'blob ' + str(len(content)).encode('ascii') + b'\0' + content
actual = hashlib.sha1(blob).hexdigest()
if actual != sys.argv[2]:
    sys.exit('校验失败，安装已中止（下载内容与发布版本不一致）')
print('✓ 代码校验通过')
PYCODE

printf '%s\n' '[3/3] 正在安装到用户目录...'
if [ -f "$APP/agent.py" ]; then
  cp "$APP/agent.py" "$APP/agent.py.bak"
fi
mv "$TMP" "$APP/agent.py"
chmod 600 "$APP/agent.py"
cat > "$BIN/sheng-agent" <<EOF
#!/bin/sh
exec "$PY" "$APP/agent.py" "\$@"
EOF
chmod 700 "$BIN/sheng-agent"
printf '\n%s\n' '✅ Sheng Agent 安装完成（未修改系统分区，也未启用远程 Shell）。'
"$BIN/sheng-agent" doctor
printf '\n%s\n' '下一步：'
printf '  %s\n' "$BIN/sheng-agent local-demo"
printf '  %s\n' "$BIN/sheng-agent setup"
printf '  %s\n' "$BIN/sheng-agent publish-demo"
printf '  %s\n' "$BIN/sheng-agent once"
