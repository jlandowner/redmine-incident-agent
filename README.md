# Redmine Incident Triage Agent

Pydantic AI を使い、Redmineに登録されたログ/メトリクスAlert IssueをIssue単位で一次トリアージする実装です。

## 処理内容

Agentは以下の順序で処理します。

1. 内容正規化
2. 既知障害との照合
3. 類似Issue検索
4. 複数Alertの相関
5. Runbook照合
6. 必要調査項目の提示

本番環境への直接アクセスは行いません。

## 状態管理

Redmine Tagを内部状態として使用します。Tag操作はAgent Toolとして公開しません。

- `agent:normalized`
  - Title/Descriptionの正規化完了後に内部処理で付与
- `agent:watermark=<journal_id>`
  - 前回Agentが処理した「Agent自身以外の最新Journal ID」

### 正規化

`agent:normalized` が存在しないIssueのみ、Agentに以下を必須実行させます。

- `update_issue_title()`
- `update_issue_description()`

両方の更新に成功した後だけ `agent:normalized` を付与します。

Description更新では、元Descriptionを `## Raw Information` 以下に完全に残すことをTool側でも検証します。

### Next Action

Next Actionは `add_note()` で記録します。

`agent:watermark=N` が存在する場合、Agent自身以外のJournal IDが `N` を超えたときだけ再実行します。

Watermarkは**run開始時点のJournalスナップショット**に固定しています。Agent実行中に人間がJournalを追加した場合、そのJournalを誤って処理済みにしないためです。

## Agent Tool

LLMへ公開するToolは以下だけです。

- `get_current_issue()`
- `get_current_issue_journals()`
- `search_issues()`
- `get_issue()`
- `update_issue_title()`
- `update_issue_description()`
- `add_note()`

Tag APIは `RedmineClient` の内部処理です。

## Redmine Tags Plugin

デフォルトでは AlphaNodes `additional_tags` 系で利用される `tag_list` をIssue更新属性として送ります。

```env
REDMINE_TAG_WRITE_FIELD=tag_list
```

利用中のTag Pluginが別フィールドを使う場合は、この値または `RedmineClient.set_tags()` を変更してください。

GET時は `tags` / `tag_list` の代表的な形式を吸収します。

## Project opt-in

各Projectに以下のWikiが存在する場合のみ処理します。

```text
AgentInstruction
```

Wiki本文はProject固有RunbookとしてAgent Instructionsへ注入します。Wiki検索Toolはありません。

## 起動

```bash
cp .env.example .env
# 環境変数を設定

pip install -e .
redmine-incident-agent
```

Cron / Kubernetes CronJobから1回実行してください。常駐Schedulerは実装していません。

## vLLM

Pydantic AIの `VLLMProvider` を使用します。

```env
LLM_PROVIDER=vllm
LLM_MODEL=Qwen/Qwen3.8-27B
LLM_BASE_URL=http://vllm:8000/v1
```

AgentはTool Callingを使うため、vLLM側で利用モデルに応じた `--enable-auto-tool-choice` / `--tool-call-parser` の設定が必要です。

## 重要な実装上の性質

- Agent runはIssue単位です。
- Agent自身のJournalはNext Action再実行トリガーから除外します。
- 同一Issueを複数Workerが同時に処理する排他は、この最小実装では外部Scheduler側の責務です。
- Tag PluginはRedmine coreではないため、Tag更新部分だけAdapter境界にしています。
- `search_issues()` はRedmine Search APIで候補を取得後、同一Project・status・期間をPython側で絞ります。
