---
name: workflow-conveyor-engine
description: Long-running work-order conveyor/state machine with durable state, idempotent steps, unified notifications hooks, and a safety fuse (backup-before-restart).
---

# Workflow Conveyor Engine（長流程輸送帶 / 狀態機）

目的：把一張工單（WO）做成 **可續跑、可重跑、可驗收** 的多步驟流程；並內建最重要的保險絲：**切斷/重啟前必須先備份**。

## Use when
- 任何需要 A→B→C 多步驟、可能跑很久、會中斷、要重試的任務
- 你不想再靠「人腦記得做到哪」

## Don’t use when
- 一次性、5 分鐘內結束的小工作

## 入口（CLI）

- 初始化一個 Work Order：
  - `python3 scripts/conveyor.py init --wo WO-xxx --title "..." --steps-json steps.json --state state/WO-xxx.json`
- 推進一次（只做下一步；成功才前進）：
  - `python3 scripts/conveyor.py tick --state state/WO-xxx.json`
- 查看狀態：
  - `python3 scripts/conveyor.py status --state state/WO-xxx.json`
- 保險絲：備份後重啟（預設 dry-run）：
  - `python3 scripts/conveyor.py fuse --state state/WO-xxx.json --backup-dir ../../var/backups --do-restart-cmd "openclaw gateway restart" --dry-run`

## 需要細節時
- 讀 `references/spec.md`（狀態機規格 + 可重入策略 + 備份/重啟保險絲）
- 跑 `tests/smoke.sh`
