# Drafter evaluation

Same transcripts, same prompt, same verifier (Muse Spark Open). Facts and traps from `eval/cases.json`, matched in code.

| Case | Recording | Drafter | Run | Facts found | Traps hit | Verifier 🔴 | Verifier 🟡 | Draft s | Output tokens |
|---|---|---|---|---|---|---|---|---|---|
| case1 | lentes6 | spark | 1 | 14/14 | 0/4 | 0 | 1 | 16.2 | 4957 |
| case1 | lentes6 | spark | 2 | 14/14 | 0/4 | 0 | 1 | 16.2 | 5697 |
| case1 | lentes6 | glimmer-low | 1 | 14/14 | 0/4 | 0 | 1 | 5.3 | 1086 |
| case1 | lentes6 | glimmer-low | 2 | 14/14 | 0/4 | 0 | 1 | 3.8 | 860 |
| case2 | lentes5 | spark | 1 | 21/23 | 1/5 | 0 | 3 | 134.1 | 9397 |
| case2 | lentes5 | spark | 2 | 21/23 | 1/5 | 2 | 1 | 74.2 | 7224 |
| case2 | lentes5 | glimmer-low | 1 | 20/23 | 0/5 | 0 | 1 | 6.5 | 1428 |
| case2 | lentes5 | glimmer-low | 2 | 20/23 | 0/5 | 1 | 0 | 5.8 | 1279 |

## Details

**case1 · spark · run 1**
- Missing facts: none
- Traps hit: none

**case1 · spark · run 2**
- Missing facts: none
- Traps hit: none

**case1 · glimmer-low · run 1**
- Missing facts: none
- Traps hit: none

**case1 · glimmer-low · run 2**
- Missing facts: none
- Traps hit: none

**case2 · spark · run 1**
- Missing facts: marcha con cojera, aumento de volumen hoy
- Traps hit: football final small talk in the note

**case2 · spark · run 2**
- Missing facts: marcha con cojera, aumento de volumen hoy
- Traps hit: football final small talk in the note

**case2 · glimmer-low · run 1**
- Missing facts: ayer, marcha con cojera, aumento de volumen hoy
- Traps hit: none

**case2 · glimmer-low · run 2**
- Missing facts: ayer, marcha con cojera, aumento de volumen hoy
- Traps hit: none
