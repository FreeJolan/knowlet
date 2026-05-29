---
created_at: '2026-05-29T16:10:52Z'
enabled: true
id: 01KST81D0AN4XWQ0BX8K3QJMS4
max_items_per_run: 20
max_keep: 50
max_pending_drafts: 20
name: Stage C Dogfood Digest
output_language: zh
prompt: 'Create one concise digest draft for this source item.


  Optimize the draft for later triage and discussion, not permanent storage:

  - lead with what happened / what changed

  - preserve concrete claims, numbers, names, and links

  - include why it may matter to the user

  - avoid generic praise or hype

  - keep enough context that the user can decide: skip, save as reference, or internalize

  '
schedule:
  every: 1d
schema_version: 1
sources:
- url: https://example.com/knowlet-stage-c-dogfood
updated_at: '2026-05-29T16:10:52Z'
---

<!-- knowlet:digest-source/v1 -->

This task feeds the Stage C digest inbox. It is stored as a normal MiningTask so the existing scheduler, runner, seen-set, and draft review flow remain the single implementation path.