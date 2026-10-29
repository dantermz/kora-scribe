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
4. **Verify.** Checks that the model cannot skip review every line (see below).
5. **Review and sign.** The doctor sees each line colour-coded, edits what needs editing, and signs. Nothing is final until a human signs.

```mermaid
flowchart LR
    A[Ray-Ban Meta<br/>glasses] -->|audio| B[iPhone app]
    B --> C[Muse Voice<br/>Transcribe]
    C -->|transcript| D[Muse Glimmer<br/>drafts SOAP note]
    D --> E{Verifier<br/>4 checks}
    E -->|flags| D
    E -->|colour-coded note| F[Doctor reviews<br/>and signs]
```

## Verification: four checks

Following the verification-layer pattern from Meta's hackathon agent workshops, the checks run outside the model's control, at the moment the note tries to move forward.

| # | Check | How | What it catches |
|---|---|---|---|
| 1 | **Verbatim citation** | Code | A line citing words that do not appear in the transcript |
| 2 | **Source** | Code | Subjective lines may cite the patient; Objective, Assessment and Plan lines must cite the clinician. Catches a medication the patient *mentioned* written as if the doctor *prescribed* it |
| 3 | **Scope** | Model (Muse Spark Open) | A line that says more than its citation, e.g. "patient reports chest pain" upgraded to "angina" |
| 4 | **Coverage** | Checklist per visit type | A note that looks complete but is missing vitals, allergies, or the plan |

Each line ends up as one of:
- ✅ **Supported** by what was said
- 🟡 **Needs a look**: off-topic content, a doubtful medical term (a slip while dictating or a transcription error), or mixed sources
- 🔴 **Unsupported**: a number, finding or plan that the cited turns do not contain

Lines that cite only the patient are tagged 💬 *patient-reported*, so the clinician can tell what was measured from what was told.

## Meta AI tooling

| Component | Role |
|---|---|
| Ray-Ban Meta glasses + Wearables Device Access Toolkit | Hands-free audio capture |
| Muse Voice Transcribe (Meta Model API) | Speech to text |
| Muse Glimmer (open weights, on Modal GPU) | SOAP note drafting |
| Muse Spark Open (open weights, on Baseten) | Scope check in the verifier |
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
- [ ] SOAP drafting with Muse Glimmer
- [ ] Verifier: citation, source, scope, coverage
- [ ] Review-and-sign interface
- [ ] Synthetic test consultations with expected facts
- [ ] Demo video

### Early findings

- Diarization separated clinician and patient correctly on every turn of a synthetic 104-second consultation.
- Keyword biasing fixed clinical terms that were first misheard ("me torcí" had come out as "me siento bien"; "maléolo" now has its accent).
- The verifier flagged "pulso medio" as a doubtful term. Listening back, the clinician had actually said "pulso medio" instead of "pulso pedio": a slip while dictating, not a transcription error. Catching the clinician's own slips is useful too, and is another reason the clinician reviews before signing.
- The same audio can produce slightly different transcripts on different runs, so the stored transcript is the single reference the note is verified against.
- The Ray-Ban Meta microphone over Bluetooth was good enough for clinical dictation: in a 69-second dictation with the iPhone 2 to 3 metres away and locked halfway through, every drug and term came through correctly ("metformina", "losartán", "monofilamento", "pulso pedio", "hemoglobina glucosilada"), and so did the spoken correction of a blood pressure reading.
- The first glasses test lost everything after 31 seconds because the iPhone auto-locked and iOS suspended the app. The capture app now keeps the screen awake, records in the background, and warns the clinician if a call or another app interrupts the recording.
- Errors in the transcript itself cannot be caught by checking the note against the transcript. That is why the clinician's review and signature stay mandatory.

## Author

**Dante Alejandro Ramírez Robles**, practicing physician in Mexico's public health system, founder and solo developer of a health-tech startup building an electronic health record for public clinics.

## License

MIT. See [LICENSE](LICENSE).
