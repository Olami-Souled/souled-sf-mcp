## Shared knowledge — Olami/Souled wiki

Before answering any domain question about Salesforce schema, UTM/Meta
attribution, coach/student data, or Olami-Souled program concepts, read
`~/knowledge/wiki/index.md` first. Then pull in the specific concept pages
under `~/knowledge/wiki/concepts/` that match the topic.

This repo is the primary **producer** of SF queries in the Olami-Souled
toolchain. The wiki is authoritative; if this repo's behavior disagrees
with the wiki, the wiki wins and this repo has a bug.

Treat the wiki as authoritative on:

- Salesforce API names, including counterintuitive typos (see
  `~/knowledge/wiki/concepts/api-name-typos.md` — do NOT "fix" names like
  `emersive_learning_experience__c`, `registartion_fee__c`,
  `Current_Growth_Cyvle_Focus__c`).
- Correct field choices: `Date_Became_SO__c` is the canonical SO date;
  `SO_Date__c` and `Date_Became_Shabbos_Observant__c` do not exist.
- UTM/Meta filter: `utm_source__c IN ('facebook','ig','fb')`, not just
  `'facebook'` (misses ~30% of Meta traffic).
- Test-record exclusion: `Test_Old__c = false AND NOT Name LIKE '%test%'`.
- Tool choice: SF CLI (`sf data query --tooling`) for schema introspection;
  Windsor for reporting aggregates (see
  `~/knowledge/wiki/concepts/windsor-vs-sf-cli.md`).

If the wiki is missing a topic that comes up here, flag it — the next
ingest pass should capture it. Wiki repo: github.com/Olami-Souled/knowledge.