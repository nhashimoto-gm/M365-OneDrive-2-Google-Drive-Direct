# M365 OneDrive → Google Drive Direct Migration Tool

Microsoft 365 Business の OneDrive データを、ZIP化せずにファイル単位で Google Drive へ直接移行するツールです。
フォルダ構造をそのまま Google Drive 上に再現し、移行後すぐにファイルを開ける状態にします。

---

## ZIP版との設計比較

本ツールは [M365-OneDrive-2-Google-Drive-Migration-Tool](https://github.com/nhashimoto-gm/M365-OneDrive-2-Google-Drive-Migration-Tool) の後継として設計されています。

### アーキテクチャの違い

```
【ZIP版】
OneDrive → ダウンロード → ZIP圧縮（4GBチャンク） → Google Drive にアップロード

【Direct版（本ツール）】
OneDrive → ダウンロード → Google Drive に直接アップロード（フォルダ構造を再現）
```

### 機能比較表

| 項目 | ZIP版 | Direct版（本ツール） |
|------|-------|---------------------|
| **Google Drive 上の形式** | ZIP ファイル | フォルダ＋個別ファイル |
| **フォルダ構造** | ZIP 内部に保持（展開が必要） | Google Drive 上に完全再現 |
| **移行後のアクセス** | ZIP を展開してから参照 | そのまま開ける |
| **ローカルストレージ** | 4GB ZIP が一時蓄積 | 50MB超のファイルのみ一時保存→即削除 |
| **再開の粒度** | チャンク単位 | **ファイル単位**（より細かく再開可能） |
| **CPU 使用率** | 中（ZIP圧縮あり） | **低（圧縮なし）** |
| **RAM 使用量** | 低（ZIPへストリーミング） | 低（50MB未満はオンメモリ、以上はtmp） |
| **VPS実行** | 可能 | **推奨（PCレス運用が容易）** |
| **適したデータ量** | 大容量（TB級） | 中〜大容量（数十GB〜TB） |

### Direct版の設計思想

ZIP版の運用で判明した課題を解決するために設計されています。

**1. 展開作業の排除**
ZIP版では移行完了後に「ZIPを展開する」追加作業が発生します。Direct版はファイルが Google Drive 上にそのまま配置されるため、移行後すぐに業務利用できます。

**2. ファイル単位の再開**
ZIP版はチャンク途中で止まると同じファイルを再ダウンロードする可能性がありました。Direct版は `migration_state.json` にファイル ID 単位で完了記録を保持するため、1ファイル単位で正確に再開できます。

**3. PC を経由しないクラウド間転送**
VPS（ConoHa 等）上で実行することで、自宅 PC を介さないクラウド間転送が実現します。データセンター間の高速回線を利用でき、PC をシャットダウンしても転送が継続します。

**4. ストレージ効率**
ZIP版は最大 4GB（設定によってはそれ以上）の一時ファイルがローカルに蓄積されます。Direct版は 50MB 超のファイルのみ一時書き出しし、アップロード完了後即削除するため、ディスク使用量を最小限に抑えます。

---

## Google Drive の構成

```
マイドライブ（または指定ルートフォルダ）
├── user1@example.com/
│   ├── 画像/
│   │   └── カメラ ロール/
│   │       ├── 2023/
│   │       │   └── photo.jpg   ← そのまま開ける
│   │       └── 2024/
│   └── ドキュメント/
│       └── 報告書.docx
└── user2@example.com/
    └── ...
```

---

## システム要件

- Python 3.11 以上
- Microsoft 365 グローバル管理者アカウント
- Google アカウント（移行先）
- 実行環境: Windows / Linux / macOS（VPS での実行を推奨）

---

## セットアップ

### 1. クローンと依存パッケージのインストール

```bash
git clone https://github.com/nhashimoto-gm/M365-OneDrive-2-Google-Drive-Direct.git
cd M365-OneDrive-2-Google-Drive-Direct

python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1      # Windows

pip install -r requirements.txt
```

### 2. Azure AD アプリの登録（M365 側）

> ZIP版で設定済みの場合はそのまま流用できます。

#### 2-1. アプリ登録

1. [Azure ポータル](https://portal.azure.com) にグローバル管理者でサインイン
2. **Azure Active Directory** → **アプリの登録** → **新規登録**

   | 項目 | 値 |
   |------|-----|
   | 名前 | `OneDrive-Migration`（任意） |
   | サポートされるアカウントの種類 | この組織ディレクトリのみ |

3. 概要画面で以下をメモ:
   - **アプリケーション (クライアント) ID** → `M365_CLIENT_ID`
   - **ディレクトリ (テナント) ID** → `M365_TENANT_ID`

#### 2-2. クライアント シークレットの作成

1. **証明書とシークレット** → **新しいクライアント シークレット** → **追加**
2. 表示された **値** をコピー → `M365_CLIENT_SECRET`
   > ⚠️ 画面を離れると値が非表示になります。

#### 2-3. API アクセス許可の追加と同意

1. **API のアクセス許可** → **アクセス許可の追加** → **Microsoft Graph** → **アプリケーションの許可**
2. 以下を追加:

   | 権限 | 用途 |
   |------|------|
   | `User.Read.All` | テナントのユーザー一覧取得 |
   | `Files.Read.All` | 全ユーザーの OneDrive ファイル読み取り |

3. **「管理者の同意を与えます」** → **はい**

### 3. Google Drive API の設定

> ZIP版で取得済みの `gdrive_credentials.json` と `gdrive_token.json` がある場合は、それをコピーするだけで再認証不要です。

#### 3-1. プロジェクト作成と API 有効化

1. [Google Cloud Console](https://console.cloud.google.com) を開く
2. 新規プロジェクト作成
3. **API とサービス** → **ライブラリ** → `Google Drive API` を **有効にする**

#### 3-2. OAuth 同意画面の設定

1. **OAuth 同意画面** → User Type: **外部** → **作成**
2. アプリ名・メールアドレスを入力 → **保存して次へ**
3. **テストユーザー** に自分の Google アカウントを追加

#### 3-3. OAuth クライアント ID の作成

1. **認証情報** → **認証情報を作成** → **OAuth クライアント ID**
2. アプリの種類: **デスクトップアプリ** → **作成**
3. JSON をダウンロードし `gdrive_credentials.json` としてプロジェクトルートに保存

### 4. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集:

```env
M365_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
M365_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
M365_CLIENT_SECRET=your_client_secret_here

# 移行対象ユーザーを限定（カンマ区切り。空の場合テナント全ユーザー）
# TARGET_USERS=user1@example.com,user2@example.com

# Google Drive の保存先フォルダ ID（空の場合マイドライブ直下）
# GDRIVE_ROOT_FOLDER_ID=1aBcDeFgHiJkLmNoPqRsTuVwXyZ
```

> **Google Drive フォルダ ID の確認方法**  
> フォルダを開いた URL `https://drive.google.com/drive/folders/XXXXX` の `XXXXX` 部分がフォルダ ID です。

---

## 実行

### ローカル PC で実行

```bash
source .venv/bin/activate
python main.py
```

初回実行時はブラウザが開き Google アカウントの認証を求められます。承認後は `gdrive_token.json` にトークンが保存され、以降は自動認証されます。

### VPS で実行（推奨）

PC を介さないクラウド間転送が実現します。

#### VPS へのファイル転送

```bash
# Windows PowerShell から実行
scp -i ~/.ssh/your_key.pem -r /path/to/M365-OneDrive-2-Google-Drive-Direct \
    root@your-vps-ip:/opt/m365_migration
```

事前に **ローカルで Google 認証を完了** し、`gdrive_token.json` を同梱して転送してください（VPS にはブラウザがないため）。

#### VPS 上でセットアップ

```bash
cd /opt/m365_migration
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### tmux でバックグラウンド実行

```bash
tmux new -s migration
python main.py
# Ctrl+B → D でデタッチ（SSH切断後も継続）
```

### 進捗確認

**tmux に再接続してリアルタイム確認:**
```bash
ssh root@your-vps-ip
tmux attach -t migration
# Ctrl+B → D で再デタッチ
```

**ログを手元から確認:**
```bash
ssh root@your-vps-ip "tail -20 /opt/m365_migration/migration.log"
```

**完了ファイル数をサマリー表示:**
```bash
ssh root@your-vps-ip "python3 -c \"
import json
s = json.load(open('/opt/m365_migration/migration_state.json'))
for u, v in s.items():
    done = len(v.get('done', []))
    comp = '✓ completed' if v.get('completed') else 'in progress'
    print(f'{u}: {done} files — {comp}')
\""
```

### 中断と再開

`Ctrl+C` で安全に中断できます。進捗は `migration_state.json` にファイル単位で保存されます。

```bash
python main.py  # 続きから自動再開（完了済みファイルはスキップ）
```

---

## ファイル構成

```
M365-OneDrive-2-Google-Drive-Direct/
├── main.py          # エントリーポイント、ログ設定
├── migrator.py      # メインロジック（ユーザー列挙→ファイル転送）
├── m365_client.py   # Microsoft Graph API クライアント
├── gdrive_client.py # Google Drive API クライアント（フォルダ作成・ファイルアップロード）
├── state.py         # 進捗の保存・再開管理（ファイル単位）
├── config.py        # .env から設定読み込み
├── requirements.txt # Python 依存パッケージ
└── .env.example     # 環境変数テンプレート
```

---

## リソース使用量の目安

| リソース | 使用量 | 備考 |
|----------|--------|------|
| CPU | 5〜10% | 圧縮処理なし、ネットワーク I/O のみ |
| RAM | 200〜350 MB | 50MB未満はオンメモリ処理 |
| ディスク | 最大数 GB（一時） | 50MB超ファイルのみ、アップロード後即削除 |
| ネットワーク | 上下ともに最大帯域 | VPS実行時はデータセンター間高速転送 |

---

## 注意事項

- `.env` と `gdrive_credentials.json` は機密情報です。`.gitignore` により git 管理外です
- Google Drive API の書き込みクォータは **750 GB/日** です。大量データの場合は複数日に分けてください
- Microsoft Graph API のレート制限により大量ファイルの処理には時間がかかる場合があります
- 同名ファイルが Google Drive に既に存在する場合はスキップされます（上書きなし）

## ライセンス

MIT
