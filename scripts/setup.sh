#!/usr/bin/env bash
# TabulaSense 開発環境セットアップ（Ubuntu 24.04 / WSL2 Ubuntu 24.04 用）
#
# 使い方:
#   bash scripts/setup.sh              # ROS 2 Jazzy + Python 環境 + XLeRobot シミュレーション
#   bash scripts/setup.sh --no-ros     # ROS 2 を入れない（クラウド GPU で学習だけする場合など）
#   bash scripts/setup.sh --no-xlerobot
#
# 何度実行しても大丈夫なように、済んでいる手順は飛ばす。
set -euo pipefail

INSTALL_ROS=1
INSTALL_XLEROBOT=1
for arg in "$@"; do
  case "$arg" in
    --no-ros) INSTALL_ROS=0 ;;
    --no-xlerobot) INSTALL_XLEROBOT=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "不明なオプション: $arg" >&2; exit 1 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XLEROBOT_DIR="${XLEROBOT_DIR:-$HOME/XLeRobot}"
ROS_DISTRO=jazzy

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

. /etc/os-release
if [ "${VERSION_ID:-}" != "24.04" ]; then
  echo "警告: Ubuntu 24.04 以外（${PRETTY_NAME:-不明}）です。ROS 2 Jazzy は 24.04 向けです。" >&2
fi

step "基本ツール"
$SUDO apt-get update
$SUDO apt-get install -y git curl build-essential software-properties-common \
  python3-venv python3-pip ffmpeg locales

if [ "$INSTALL_ROS" -eq 1 ]; then
  step "ロケール (UTF-8)"
  $SUDO locale-gen en_US en_US.UTF-8
  $SUDO update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
  export LANG=en_US.UTF-8

  step "ROS 2 apt リポジトリ"
  if ! dpkg -s ros2-apt-source >/dev/null 2>&1; then
    $SUDO add-apt-repository -y universe
    ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
      | grep -F '"tag_name"' | awk -F'"' '{print $4}')
    curl -fL -o /tmp/ros2-apt-source.deb \
      "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.${VERSION_CODENAME}_all.deb"
    $SUDO dpkg -i /tmp/ros2-apt-source.deb
    $SUDO apt-get update
  else
    echo "設定済み"
  fi

  step "ROS 2 ${ROS_DISTRO} + Nav2 + slam_toolbox（時間がかかります）"
  $SUDO apt-get install -y ros-${ROS_DISTRO}-desktop ros-dev-tools \
    ros-${ROS_DISTRO}-navigation2 ros-${ROS_DISTRO}-nav2-bringup ros-${ROS_DISTRO}-slam-toolbox

  ROS_SOURCE_LINE="source /opt/ros/${ROS_DISTRO}/setup.bash"
  if ! grep -qxF "$ROS_SOURCE_LINE" "$HOME/.bashrc"; then
    echo "$ROS_SOURCE_LINE" >> "$HOME/.bashrc"
  fi
fi

step "Python 仮想環境 (.venv) と依存パッケージ"
cd "$REPO_DIR"
if [ ! -d .venv ]; then
  # ROS 2 の rclpy なども使えるように system-site-packages を有効にする
  python3 -m venv .venv --system-site-packages
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

if [ "$INSTALL_XLEROBOT" -eq 1 ]; then
  step "XLeRobot（MuJoCo モデル）"
  if [ ! -d "$XLEROBOT_DIR" ]; then
    git clone --depth 1 https://github.com/Vector-Wangel/XLeRobot.git "$XLEROBOT_DIR"
  else
    echo "既に存在: $XLEROBOT_DIR"
  fi
fi

step "動作確認"
python -c "import importlib.metadata as m, lerobot, mujoco, torch; print('mujoco', mujoco.__version__, '/ lerobot', m.version('lerobot'), '/ cuda', torch.cuda.is_available())"

cat <<EOF

完了しました。新しいターミナルで作業を始めるときは:
  cd $REPO_DIR && source .venv/bin/activate

確認コマンド:
  ros2 run demo_nodes_cpp talker / ros2 run demo_nodes_py listener
  python -m mujoco.viewer --mjcf $XLEROBOT_DIR/simulation/mujoco/scene.xml
EOF
