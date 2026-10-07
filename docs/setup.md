# 開発環境セットアップ（Step 0）

README の「Step 0：開発環境の準備」を実際に構築した手順。Windows + WSL2 で動作確認済み。

| 項目 | バージョン |
|---|---|
| OS | Ubuntu 24.04（Windows では WSL2） |
| ROS 2 | Jazzy（+ Nav2, slam_toolbox） |
| Python | 3.12（Ubuntu 標準）＋ `.venv` |
| MuJoCo | 3.15.0 |
| LeRobot | 0.6.1（PyTorch 2.11, CUDA 13） |
| ロボットモデル | [XLeRobot](https://github.com/Vector-Wangel/XLeRobot) `simulation/mujoco/` |

## 早見表：自動セットアップ

1〜2 が済んでいれば、残りは次の 1 コマンドで構築できる。

```bash
cd ~/TabulaSense
bash scripts/setup.sh            # クラウド GPU で学習だけする場合は --no-ros
```

## 1. WSL2 + Ubuntu 24.04（Windows のみ）

PowerShell（管理者）で:

```powershell
wsl --install -d Ubuntu-24.04
```

再起動後、スタートメニューの「Ubuntu 24.04」を開いてユーザーを作る。
NVIDIA GPU を使う場合は **Windows 側に** NVIDIA ドライバーを入れるだけでよい（WSL 内には入れない）。
`nvidia-smi` で GPU が見えれば OK。

> 以降のコマンドはすべて **Ubuntu のターミナル**（`ユーザー名@PC名:~$`）で実行する。
> PowerShell / コマンドプロンプトで実行すると `~` が `C:\Users\...` になり、ファイルが見つからない。

## 2. Git / GitHub（SSH）

```bash
sudo apt update && sudo apt install -y git
git config --global user.name "名前"
git config --global user.email "GitHub に登録したメールアドレス"
ssh-keygen -t ed25519          # 質問は全部 Enter
cat ~/.ssh/id_ed25519.pub      # 表示された 1 行を https://github.com/settings/keys に登録
ssh -T git@github.com          # 「Hi <ユーザー名>!」と出れば OK
git clone git@github.com:Ryotaro-Fujiwara-san/TabulaSense.git
```

初回接続時の指紋 `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU` は GitHub 公式のもの。`yes` と入力する。

## 3. ROS 2 Jazzy

[公式手順](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)と同じ。

```bash
# ロケール
sudo apt update && sudo apt install -y locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

# apt リポジトリ
sudo apt install -y software-properties-common curl
sudo add-apt-repository -y universe
export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F\" '{print $4}')
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo $VERSION_CODENAME)_all.deb"
sudo dpkg -i /tmp/ros2-apt-source.deb

# 本体 + Step 5 で使うパッケージ
sudo apt update && sudo apt upgrade -y
sudo apt install -y ros-jazzy-desktop ros-dev-tools
sudo apt install -y ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox

echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

確認: ターミナルを 2 つ開き、`ros2 run demo_nodes_cpp talker` と `ros2 run demo_nodes_py listener` を実行。
listener に `I heard: [Hello World: N]` が流れれば OK。

## 4. Python 仮想環境 + MuJoCo + LeRobot

ROS 2 が使う Ubuntu 標準の Python を汚さないよう、ML 系は `.venv` に分ける。
`--system-site-packages` を付けるのは、`.venv` の中からも ROS 2 の `rclpy` を import できるようにするため。

```bash
sudo apt install -y python3-venv python3-pip ffmpeg
cd ~/TabulaSense
python3 -m venv .venv --system-site-packages
source .venv/bin/activate      # 先頭に (.venv) が付く
pip install -U pip
pip install -r requirements.txt
```

確認:

```bash
python -c "import lerobot, mujoco, torch; print('mujoco', mujoco.__version__, '/ cuda', torch.cuda.is_available())"
# mujoco 3.15.0 / cuda True   （GPU がなければ False でも可）
```

**毎回の作業開始時:**

```bash
cd ~/TabulaSense && source .venv/bin/activate
```

`.venv` に入っていないと `python` コマンドがない（`Command 'python' not found`）。

## 5. XLeRobot シミュレーション

```bash
cd ~ && git clone --depth 1 https://github.com/Vector-Wangel/XLeRobot.git
cd ~/TabulaSense && source .venv/bin/activate

# モデルを表示
python -m mujoco.viewer --mjcf ~/XLeRobot/simulation/mujoco/scene.xml

# キーボード操作（scene.xml をカレントディレクトリから読むので cd が必要）
cd ~/XLeRobot/simulation/mujoco
python xlerobot_mujoco.py
```

> ⚠️ XLeRobot の `simulation/mujoco/requirements.txt` は **インストールしない**。
> mujoco 3.3.0 / huggingface-hub 0.31 などに固定されていて、LeRobot 0.6.1 と衝突する。
> 必要なのは `mujoco-python-viewer` と `glfw` だけで、本リポジトリの `requirements.txt` に含めてある。

| 操作 | キー |
|---|---|
| 台車 前 / 後 | `Home` / `End` |
| 台車 左 / 右 | `Delete` / `Page Down` |
| 台車 回転 | `Insert` / `Page Up` |
| 左アーム 関節 1〜3 | `Q`/`A`, `W`/`S`, `E`/`D` |
| 右アーム 関節 1〜3 | `U`/`J`, `I`/`K`, `O`/`L` |

ノート PC では `Fn` との同時押しが必要な場合がある。

## 6. クラウド GPU（Step 3 から）

RunPod / Lambda / Vast.ai / GCP 等で Ubuntu + NVIDIA GPU のマシンを借り、SSH で入って:

```bash
git clone git@github.com:Ryotaro-Fujiwara-san/TabulaSense.git
cd TabulaSense
bash scripts/setup.sh --no-ros
```

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `ssh-keygen` で `Too many arguments` | Windows のコマンドプロンプトで `# コメント` 付きのまま実行した。Ubuntu で、コマンドだけを入力する |
| `git clone` で `Permission denied (publickey)` | 公開鍵を GitHub に登録していない（手順 2） |
| `Please type 'yes', 'no' or the fingerprint` | `y` ではなく `yes` と入力する |
| `ParseXML: Error opening file 'C:\Users\...\scene.xml'` | Windows 側で実行している、または XLeRobot を clone していない。Ubuntu で手順 5 をやり直す |
| `Command 'python' not found` | `.venv` に入っていない。`source ~/TabulaSense/.venv/bin/activate` |
