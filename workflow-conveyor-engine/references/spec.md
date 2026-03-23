# workflow-conveyor-engine — Spec

## 1. 目標

把「長流程任務」包成一個可落地的狀態機：
- 可續跑（中斷後回來繼續）
- 可重跑（同一步驟重跑不破壞既有成果）
- 可驗收（每一步有可跑的驗收點）
- 可觀測（記錄 step log、結果摘要）

並提供核心保險絲：
- **需要切斷/重啟時：先備份 → 再重啟**
- 備份失敗：禁止重啟，改為告警

## 2. 狀態檔（state JSON）

每個 WO 一個 state 檔，最小欄位：
- `wo`：工單 ID
- `title`
- `created_at`
- `updated_at`
- `current_step`：整數 index
- `steps[]`：步驟定義（見下）
- `history[]`：每次 tick 的結果（時間、step、成功/失敗、訊息）

步驟定義（每個 step）：
- `id`：step id
- `title`：人類可讀
- `run`：要執行的命令（string）或 script path
- `verify`：驗收命令（可選）
- `idempotency_key`：用於去重/避免重跑造成覆寫（可選）

## 3. Tick（推進規則）

- 一次 tick 只處理 `current_step` 對應那一步
- 該步驟成功（run 成功 + verify 成功若有）→ `current_step += 1`
- 失敗 → 停在原地，寫入 history，讓下次 tick 重試

## 4. 可重入（Idempotency）

硬規則：步驟腳本必須可重入。
- 任何「寫檔/覆寫」要先檢查輸入是否為空、或目標是否存在
- 任何「發通知」必須有上游去重（message_id / task_id / TTL）

## 5. 保險絲：backup-before-restart（Fuse）

`fuse` 子命令：
1) 先執行備份：把以下內容打包存檔（最小集合）
   - WO state JSON
   - BOOT.md / MEMORY.md（可選）
   - 相關輸出檔清單（由 state/steps 提供或手動指定）
2) 備份成功才允許執行 restart command
3) 預設 dry-run，必須顯式指定才真的重啟

備份輸出：
- `backup_dir/workflow-conveyor-engine/<wo>/<timestamp>.tar.gz`

## 6. 測試（必備）

- smoke test：用一個兩步驟的假 WO，跑到完成
- fuse test：在 dry-run 下確認會產生備份檔，但不會真的重啟

## Changelog
- 2026-03-23：初版
