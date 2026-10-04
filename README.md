# TabulaSense

> カメラでテーブルの上を認識し、**片付け**と**拭き上げ**を自動で行う掃除ロボット

![status](https://img.shields.io/badge/status-開発中-orange)

## 概要

TabulaSense は、テーブルの上にある「片付けるべき物」と「拭き取るべき汚れ」をカメラで見分け、
アームで物を回収したあと、ワイパー／モップでテーブル表面を自動で拭き上げるロボットです。
また下げ膳なども行います。

## 開発目標（MVP）

XLeRobotをMuJoCoでシミュレーションし、最新論文を実装して精度向上も目指す。
さらに、XLeRobotを自費で購入し組み立てる。そして顧客で試験導入しながら精度向上を目指す。
YORのシミュレーションモデルを作成し、YOR(https://yourownrobot.ai/)を助成金で購入しさらにPoCを行う。

全体の計画は [docs/roadmap.md](docs/roadmap.md) にあります。いまはフェーズ 0（シミュレーション環境）が終わったところです。

![overview](docs/images/overview_cam.png)

## できること（現時点）

| 項目 | 内容 |
|---|---|
| シーン | XLeRobot（上流の MJCF をそのまま読み込む）＋テーブル＋食器 4 種＋汚れ＋下げ膳用ビン |
| 拭き取り | 右手にスポンジを持たせてある。スポンジが天板に触れながら動くと、触れた汚れが薄くなる |
| 環境 | Gymnasium 環境 `TabulaSense/TableClean-v0`（行動 15 次元、観測は真値） |
| カメラ | `head_cam`（実機の頭カメラ相当）、`top_cam`（真上）、`overview_cam`（全体） |
| 認識 | 真値から「物 / 汚れ / テーブル / ロボット」のラベル画像を作る（検出モデルの正解データ用） |

| 頭カメラ | ラベル画像（赤＝回収する物、茶＝汚れ） |
|---|---|
| ![head](docs/images/head_cam.png) | ![labels](docs/images/head_cam_labels.png) |

## セットアップ（自分の PC で動かす）

必要なもの: **Python 3.10 以上**と **Git**。動作確認は Python 3.11 / MuJoCo 3.14 で行いました。
GPU は不要です。

### Windows（PowerShell）

```powershell
git clone https://github.com/Ryotaro-Fujiwara-san/TabulaSense.git
cd TabulaSense
py -m venv .venv
.venv\Scripts\Activate.ps1          # 「スクリプトの実行が無効」と出たら下の注を参照
pip install -e ".[dev]"
python scripts/fetch_xlerobot.py      # XLeRobot の MuJoCo モデルを third_party/ に取得（約 30MB）
pytest                                # 7 件のテスト
python scripts/view.py --demo         # ウィンドウが開いてロボットが拭き掃除をする
```

> 注: `Activate.ps1` が実行できないときは、一度だけ
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` を実行してください。

### macOS / Linux

```bash
git clone https://github.com/Ryotaro-Fujiwara-san/TabulaSense.git
cd TabulaSense
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
python scripts/fetch_xlerobot.py
pytest
python scripts/view.py --demo         # macOS では python の代わりに mjpython
```

### 画面のないサーバー（クラウド、Docker、CI）

画像を描画するには OpenGL を用意して `MUJOCO_GL` を指定します。

```bash
sudo apt-get install -y libegl1 libosmesa6   # Ubuntu / Debian
export MUJOCO_GL=egl                         # GPU があれば egl、なければ osmesa
```

## 動かしてみる

```bash
# 3 台のカメラ画像とラベル画像を outputs/scene/ に保存
python scripts/render_scene.py --seed 0

# スポンジで汚れを拭き取る手書きデモ（動画保存には pip install imageio imageio-ffmpeg）
python scripts/demo_wipe.py --video outputs/demo_wipe.mp4
```

```python
import gymnasium as gym
import tabulasense  # 環境の登録

env = gym.make("TabulaSense/TableClean-v0", render_mode="rgb_array")
obs, info = env.reset(seed=0)
obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
print(info)  # {'objects_on_table': 4, 'objects_in_bin': 0, 'objects_dropped': 0, 'dirt_remaining': 3.0}
```

ウィンドウで見るときは `python scripts/view.py`（マウスで視点を回せます）。
自分のコードからは `render_mode="human"` を指定します。

### 行動と観測

- 行動（15 次元、すべて -1〜1）
  - 0〜2: 台車の速度（ロボットから見て 前・左・旋回）
  - 3〜8: 右腕 6 関節の目標角の増分（1 ステップ最大 0.05 rad）
  - 9〜14: 左腕 6 関節の目標角の増分
  - 制御は 20Hz（物理は 500Hz）
- 観測（辞書）
  - `robot`: 腕の角度・角速度、台車の位置・向き・速度（30 次元）
  - `objects`: 物体ごとの位置と [テーブル上, ビン内, 落下] フラグ
  - `stains`: 汚れごとの位置・半径・残り具合（0〜1）
- 報酬: ビンに入れた物 +1、落とした物 −0.5、拭き取った量に比例して加点、全部片付いて拭き終えたら +5

関節名の `_R` / `_L` は上流モデルの名前をそのまま使っています。スポンジは `_R` 側の手に付いています。

## 上流モデルへの調整

`third_party/` の XLeRobot のファイルは書き換えず、読み込んだあとに `sim/scene.py` で次の点を直しています。

- 台車を表す箱が既定の密度から約 120kg になっていたので、8kg にした（`SceneConfig.cart_mass`）
- オムニホイールが普通の車輪として床と接触し、横移動を妨げていたので、見た目だけにした
- 台車の速度制御のゲインを上げた（kv=10 → 300）
- 頭の 2 関節に駆動がなく重力で垂れていたので、位置制御を足した（`env.set_head_pose()`）

## ディレクトリ構成

```
TabulaSense/
├── src/tabulasense/
│   ├── sim/scene.py          シーンの組み立て（MjSpec）
│   ├── sim/env.py            Gymnasium 環境
│   └── perception/oracle.py  真値のラベル画像（検出モデルの正解・比較用）
├── scripts/                  XLeRobot の取得、表示、描画、デモ
├── tests/
├── docs/roadmap.md           開発計画（シミュレーション → XLeRobot 実機 → 顧客試験 → YOR）
└── third_party/              外部リポジトリ（git 管理しない）
```
