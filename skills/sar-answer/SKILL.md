---
name: "sar-answer"
key: "sar-answer"
description: "sArthI's knowledge retrieval skill. Answers runtime, pipeline, and data engineering questions by searching the team knowledge base, querying BigQuery schema, looking up Jira history, and tracing lineage. Returns a structured answer with cited sources."
allowed-tools: [Read, Glob, Grep, mcp__plugin__wibey_mcp-jira__nlp_based_search, mcp__sarthi-bq__bq_schema, mcp__sarthi-bq__bq_search_tables, mcp__sarthi-bq__bq_list_tables, mcp__sarthi-bq__bq_list_datasets, mcp__sarthi-bq__bq_query]
metadata:
  author: "akiran"
  version: "1.0.0"
  part-of: "sarthi"
  status: "placeholder"
---

# sar-answer — Runtime Knowledge Answerer

## Purpose
When the team asks sArthI a question about the platform — "why does this DAG run
on Tuesdays?", "what tables does the CA backfeed write to?", "has this error happened
before?" — this skill retrieves the answer from structured knowledge, Jira history,
and live BigQuery schema.

## Status: PLACEHOLDER

## TODO — implement:

- [ ] Read `envelope.source.fetched_content` to understand the question
- [ ] Search `~/.wibey/knowledge/` (subject-areas.json, repo-registry.json, lineage/)
- [ ] Look up BigQuery table schema if the question mentions a table name
  - `mcp__sarthi-bq__bq_schema` with table/dataset/project args
  - Use `mcp__sarthi-bq__bq_search_tables` if table name is unknown (pattern search)
  - Use `mcp__sarthi-bq__bq_query` for data samples or row-count queries
- [ ] Search Jira for related tickets using NLP search (mcp-jira nlp_based_search)
- [ ] Search `~/.wibey/knowledge/resolution-patterns.json` for relevant past incidents
- [ ] Search `~/.wibey/knowledge/known-issues.json` for matching symptoms (auth failures, setup issues, MCP errors)
- [ ] Compose a structured answer with cited sources
- [ ] Add answer to `envelope.artifacts[]`

## Answer format
```
**Question:** <original question>

**Answer:** <direct answer in 1-3 sentences>

**Details:**
- <detail 1>
- <detail 2>

**Sources:**
- Knowledge base: <file/section>
- Jira: <KEY> — <summary>
- BigQuery schema: <project.dataset.table>
```

## Expected output
- `envelope.artifacts` updated with:
```json
{
  "type": "answer",
  "question": "<original question>",
  "answer": "<answer text>",
  "sources": ["<source 1>", "<source 2>"]
}
```
