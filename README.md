# KORA Scribe

![Meta Global AI Developer Hackathon 2026](https://img.shields.io/badge/Meta_Global_AI_Hackathon-2026-0866FF)
![Track](https://img.shields.io/badge/Track-Startup-6E40C9)
![Models](https://img.shields.io/badge/Models-Muse_Glimmer_·_Muse_Spark_Open-1F883D)
![Status](https://img.shields.io/badge/Status-In_progress-F59E0B)
![License: MIT](https://img.shields.io/badge/License-MIT-lightgrey)

**Hands-free clinical scribe for public-sector doctors in Mexico.** *(Work in progress: this README describes the design; see Status for what is built so far.)*

Ray-Ban Meta glasses capture the consultation, Muse Voice Transcribe turns it into text, Muse Glimmer drafts a SOAP note, and a verifier agent checks every line against the transcript before the doctor reviews and signs.

> **Documentation, not decisions.** KORA Scribe never diagnoses, recommends treatment, or gives medical advice. It only structures what the clinician and patient actually said, and the clinician signs every note.

Built for the **Meta Global AI Developer Hackathon 2026** (Startup Track, *Build for Your World*).

---

## The problem

In Mexico's public health system, a primary-care doctor sees a patient every 15 to 20 minutes and spends a large share of each visit typing into the record instead of looking at the patient. Notes end up short, late, or copied from the previous visit.

General-purpose AI scribes make this worse in a quieter way: they produce notes that *look* complete but quietly add things nobody said, such as an inferred diagnosis, a rounded number, or a medication the patient mentioned treated as if the doctor prescribed it. A note that reads well but is not grounded is more dangerous than a short one.

## What KORA Scribe does

1. **Capture.** The doctor wears Ray-Ban Meta glasses. Audio is captured hands-free on the paired iPhone.
2. **Transcribe.** Muse Voice Transcribe produces a timestamped transcript.
3. **Draft.** Muse Glimmer (open weights, self-hosted) drafts a structured SOAP note. Every line must cite the transcript segment it comes from.
4. **Verify.** Checks that the model cannot skip review every line, and flag where the transcript itself may be missing speech (see below).
5. **Review and sign.** The doctor sees each line colour-coded, edits what needs editing, and signs. Nothing is final until a human signs.

```mermaid
flowchart LR
    A[Ray-Ban Meta<br/>glasses] -->|audio| B[iPhone app]
    B --> C[Muse Voice<br/>Transcribe]
    C -->|transcript| D[Muse Glimmer<br/>drafts SOAP note]
    D --> E{Verifier<br/>6 checks}
    E -->|flags| D
    E -->|colour-coded note| F[Doctor reviews<br/>and signs]
```

Prompts and clinical output are in Spanish on purpose: the consultations and the notes are for Mexican clinicians. Code and documentation are in English.

## Verification: six checks

Following the verification-layer pattern from Meta's hackathon agent workshops, the checks run outside the model's control, at the moment the note tries to move forward.

| # | Check | How | What it catches |
|---|---|---|---|
| 1 | **Verbatim citation** | Code | A line citing words that do not appear in the transcript |
| 2 | **Source** | Code | Subjective lines may cite the patient; Objective, Assessment and Plan lines must cite the clinician. Catches a medication the patient *mentioned* written as if the doctor *prescribed* it |
| 3 | **Scope** | Model (Muse Spark Open), two passes | A line that says more than its citation, e.g. "patient reports chest pain" upgraded to "angina" |
| 4 | **Coverage** | Checklist per visit type | A note that looks complete but is missing vitals, allergies, or the plan |
| 5 | **Lost audio** | Code | A clinician question with no recorded answer, or a long stretch with no transcribed speech: signs that the patient said something the transcript never captured |
| 6 | **Recap** | Model (Muse Spark Open), two passes | The clinician recaps the history aloud; the recap is compared fact by fact with what was transcribed from the patient. A different value for the same fact (where, when, how much, took it or not) flags the line: one of the two was misheard |

Each line ends up as one of:
- ✅ **Supported** by what was said
- 🟡 **Needs a look**: off-topic content, a doubtful medical term (a slip while dictating or a transcription error), or mixed sources
- 🔴 **Unsupported**: a number, finding or plan that the cited turns do not contain

Lines that cite only the patient are tagged 💬 *patient-reported*, so the clinician can tell what was measured from what was told.

## Review and sign

A local page (`review/index.html`, served by `scripts/review_server.py`) puts the note and the transcript side by side:

- Long turns are split into phrases using the word timing in the transcription events, so each line cites the exact phrase it comes from.
- Click a line to highlight the phrases it cites; press ▶ to hear exactly those seconds of audio.
- Lost-audio warnings sit in the transcript where the speech went missing, with a button to play that stretch.
- The clinician can correct, accept, remove or add lines. Every change is kept next to what the model proposed.
- **Signing is blocked** until every 🔴 line has been decided and every lost-audio warning has been reviewed.
- The signed record (`<case>.signed.json`) holds the final note, where each line came from (model, corrected by the clinician, added by the clinician), the full audit of changes, and SHA-256 hashes of the note and of the transcript it was checked against.

```bash
python scripts/run_pipeline.py audio/consulta.wav    # transcribe, draft, verify
python scripts/review_server.py audio/consulta       # review and sign at http://localhost:8770
```

Everything runs on the clinician's machine; the page talks only to the local server.

## Evaluation: which model drafts

`eval/eval.py` drafts the same transcripts with each model, verifies every note with the same verifier (Muse Spark Open), and scores it in code against the expected facts and traps written for each synthetic consultation (`eval/cases.json`, from `eval/dictados_sinteticos.md`). Same prompt for both models, two runs each:

| | Muse Spark Open | Muse Glimmer (reasoning low) |
|---|---|---|
| Case 1, hypertension: expected facts found | 14/14 · 14/14 | 14/14 · 14/14 |
| Case 2, ankle sprain: expected facts found | 21/23 · 21/23 | 20/23 · 20/23 |
| Traps hit (case 1 + case 2) | 1/9 · 1/9 (small talk about a football final written into the plan) | **0/9 · 0/9** |
| Drafting time | 16–134 s | **4–7 s** |
| Output tokens per note | 5,000–9,400 | **~900–1,400** |

Two of the 23 facts in case 2 were never in the transcript (the glasses lost "cojeando" and "hoy amaneció más hinchado"), so no drafter can find them; Glimmer also left out "ayer", which only the clinician's recap said. **Muse Glimmer drafts; Muse Spark Open verifies**, so the note is always checked by a different model from the one that wrote it.

The first prompt produced a useful lesson. Its rules ("write only what was said, add nothing") were read literally by Glimmer, which copied the transcript into the note instead of writing one, at any reasoning level; Spark Open wrote proper clinical lines but filled in a word it could not understand. One prompt fix helped both: rewrite in clinical style with a short example, and write **[ininteligible]** instead of guessing.

## Running Muse Glimmer

Glimmer runs on a single Modal GPU (RTX PRO 6000, NVIDIA's NVFP4 checkpoint, SGLang), deployed with the open-source scripts in [jscott3201/llm-tuning](https://github.com/jscott3201/llm-tuning/tree/main/glimmer). Two changes were needed to put the endpoint behind an API key: attach a Modal secret holding `API_KEY` to the serving class, and send that key on the server's own startup calls (health check, warm-up and snapshot requests), which otherwise fail with 401 and keep the container restarting. The endpoint scales to zero after 15 idle minutes; the whole hackathon used a few dollars of GPU time.

Then point the drafter at it in `.env` (see `.env.example`): `DRAFT_BASE_URL`, `DRAFT_API_KEY`, `DRAFT_MODEL=muse-glimmer`, `DRAFT_REASONING=low`.

## Meta AI tooling

| Component | Role |
|---|---|
| Ray-Ban Meta glasses + Wearables Device Access Toolkit | Hands-free audio capture |
| Muse Voice Transcribe (Meta Model API) | Speech to text |
| Muse Glimmer (open weights, on Modal GPU) | SOAP note drafting |
| Muse Spark Open (open weights, on Baseten) | Verifier (scope and recap checks), and the baseline drafter in the evaluation |
| Muse Code | Development |

Note generation and verification run on open-weight models. Mexico's health-record regulation (NOM-024) pushes toward data sovereignty, and clinical notes are among the most sensitive records a system holds, so a deployment path that does not depend on a closed hosted API matters.

## Data policy

- **Synthetic data only.** Every consultation in this repository and in the demo is fictional and was written for testing. No real patient data is used, stored, or sent to any API.
- No credentials in the repository. API keys live in a local `.env` file, which is git-ignored.

## Built during the hackathon vs. pre-existing

Judges must be able to see what is new, so this is explicit.

**Built during the hackathon (Oct 27 to Nov 4, 2026):** all the code in this repository. Work started on October 27; the commit history shows what was added and when, and the Status section below shows what is done and what is still in progress.

**Pre-existing (not in this repository):** the author's electronic health record, already in use in public clinics in Mexico. None of its code is included here or presented as hackathon work. Exporting signed notes to it through a standard interface (FHIR) is planned after the hackathon.

## Status

🚧 In progress. This README is the specification and will be updated as each part ships.

- [x] Transcription test with Muse Voice Transcribe: Spanish, speaker diarization, turn IDs and timestamps (`scripts/transcribe_file.py`)
- [x] Glasses audio capture on iPhone (`ios/`): records through the Ray-Ban Meta microphone over Bluetooth, straight to 16 kHz mono WAV
- [x] SOAP drafting with citations (`scripts/draft_note.py`), on Muse Glimmer self-hosted on Modal, or Muse Spark Open
- [x] Evaluation of both drafters against expected facts and traps (`eval/eval.py`)
- [x] Verifier: citation, source, scope, coverage, lost audio, recap (`scripts/verify_note.py`)
- [x] Phrase-level citations: long turns split by sentence and pause, no re-transcription (`scripts/segment_turns.py`)
- [x] One-command pipeline: audio to verified note (`scripts/run_pipeline.py`)
- [x] Review-and-sign interface: cited turns, audio playback per turn, lost-audio warnings, edits with audit trail, blocked signature (`review/`, `scripts/review_server.py`)
- [x] Synthetic test consultations with expected facts (`eval/dictados_sinteticos.md`, `eval/cases.json`)
- [ ] Demo video

### Early findings

- Diarization separated clinician and patient correctly on every turn of a synthetic 104-second consultation.
- Keyword biasing fixed clinical terms that were first misheard ("me torcí" had come out as "me siento bien"; "maléolo" now has its accent).
- The verifier flagged "pulso medio" as a doubtful term. Listening back, the clinician had actually said "pulso medio" instead of "pulso pedio": a slip while dictating, not a transcription error. Catching the clinician's own slips is useful too, and is another reason the clinician reviews before signing.
- The same audio can produce slightly different transcripts on different runs, so the stored transcript is the single reference the note is verified against.
- The Ray-Ban Meta microphone over Bluetooth was good enough for clinical dictation: in a 69-second dictation with the iPhone 2 to 3 metres away and locked halfway through, every drug and term came through correctly ("metformina", "losartán", "monofilamento", "pulso pedio", "hemoglobina glucosilada"), and so did the spoken correction of a blood pressure reading.
- The first glasses test lost everything after 31 seconds because the iPhone auto-locked and iOS suspended the app. The capture app now keeps the screen awake, records in the background, and warns the clinician if a call or another app interrupts the recording.
- With the glasses, the patient's voice one metre away is much weaker than the wearer's. In a synthetic consultation the chief complaint ("me torcí el tobillo") never reached the transcript, and the note still passed every line check: a verifier can only check a note against what was transcribed. This led to the fifth check, which flags unanswered clinician questions and long silences so the clinician knows what to confirm, and to a simple practice that fixes it at the source: the clinician recaps the history aloud before examining.
- A model-based check is not deterministic: the same line ("Temperatura 36.8 °C") passed on one run and was flagged on another. Numbers, sources and lost audio are therefore checked in code; the model is a second layer.
- Listening back is part of the review. The transcript had "poquito pero con gelada" (unintelligible); the draft papered over it as "pudo caminar poquito pero con dificultad", and the scope check flagged that line 🔴. Playing the two cited turns from the review page, the patient's word was clearly "cojeando". The clinician corrected the line in seconds, and the signed record keeps both versions.
- The clinician's recap turned out to be a second, clearer source for the patient's history. Comparing it with the patient's transcribed words caught errors no other check could see: in one consultation the transcript had the patient say "**no** tomé ni ibuprofeno" while she had said she *did* take one (the recap says "tomaste ibuprofeno"); in another, "en la mañana" against the recap's "en la farmacia". Both are flagged for the clinician to listen to and decide; neither version is picked automatically.
- Model-based checks keep varying between runs, so the recap check lists every fact of the recap with a verdict and runs twice, merging what it finds. Across three runs on two consultations it found the same two conflicts every time and flagged nothing where the recap agreed.
- Muse Glimmer invents too, just differently. In one consultation the clinician stumbled ("si es una semana…" before "si en una semana no mejora…"); Glimmer turned that false start into "reposo deportivo por una semana", replacing the two weeks the clinician actually prescribed. The scope check missed it once, so it now sees the rest of a cut sentence and runs twice: the line was flagged 🔴 in four runs out of four. Spark Open's failure mode was filling in a word it could not understand; Glimmer's was reading a stumble as an order. Both are why the verifier is a different model from the drafter, and why the clinician signs.
- Errors in the transcript itself cannot be caught by checking the note against the transcript. That is why the clinician's review and signature stay mandatory.

## Author

**Dante Alejandro Ramírez Robles**, practicing physician in Mexico's public health system, founder and solo developer of a health-tech startup building an electronic health record for public clinics.

## License

MIT. See [LICENSE](LICENSE).
