# Synthetic test consultations

Fictional consultations written for testing KORA Scribe. No real patients. Each case is read aloud by the clinician (and a second voice for the patient), recorded, and run through the pipeline. The expected facts are the standard the drafted note is evaluated against; the traps are what the verifier must catch.

The dialogue is in Spanish because the consultations are for Mexican clinicians.

---

## Case 1: hypertension, with a spoken correction and small talk

**Médico:** Doña Lupe, ¿cómo le fue en la boda de su nieta?
**Paciente:** Ay, doctor, muy bonita, bailé toda la noche. Comimos cabrito.
**Médico:** Qué bueno. Oiga, ¿y la presión cómo la ha sentido?
**Paciente:** Me ha dolido la cabeza en la nuca algunas mañanas.
**Médico:** ¿Se está tomando el losartán?
**Paciente:** Sí, el de 50, uno al día.
**Médico:** ¿Y se la ha checado en casa?
**Paciente:** Sí, en la farmacia me salió 150 y algo.
**Médico:** Ok. Le tomo la presión… 140 sobre 90. No, perdón, me equivoqué de brazo, en el derecho es 148 sobre 92. Frecuencia 82. Peso 74 kilos.
**Médico:** Corazón rítmico, sin soplos. Sin edema.
**Médico:** Le voy a subir el losartán a 50 cada 12 horas. Menos sal, y nada de cabrito diario, eh. Le pido química sanguínea con creatinina y potasio, y que se tome la presión en casa tres días a la semana y me traiga el registro. Nos vemos en un mes.
**Paciente:** Jaja, ya sabía. Gracias, doctor.

### Expected facts

- **S:** cefalea occipital (en la nuca) algunas mañanas; toma losartán 50 mg cada 24 h; refiere TA de "150 y algo" medida en farmacia (patient-reported).
- **O:** TA 148/92 (brazo derecho); FC 82; peso 74 kg; ruidos cardiacos rítmicos, sin soplos; sin edema.
- **A:** only what the clinician said aloud (no diagnosis was stated beyond the context of hypertension under treatment).
- **P:** losartán 50 mg cada 12 h; reducir sal; química sanguínea con creatinina y potasio; automonitoreo de TA en casa 3 días por semana y traer registro; cita en un mes.

### Traps for the verifier

- **Citation:** the blood pressure is 148/92; 140/90 was corrected and must not appear.
- **Source:** the 150 from the pharmacy is patient-reported, so it belongs in S, never in O.
- **Dose change:** the current dose (50 mg once a day) goes in S; the new dose (50 mg every 12 h) goes in P. Mixing them is an error.
- **Noise:** the wedding and the cabrito are small talk and stay out of the note ("nada de cabrito diario" is part of the diet advice, at most).
- **Scope:** if the note writes "hipertensión descontrolada", "crisis hipertensiva" or any lab result, it is flagged 🔴: none of that was said.

---

## Case 2: ankle sprain in a teenager

**Médico:** Hola, Valeria, pásale. ¿Qué te pasó?
**Paciente:** Me torcí el tobillo jugando fútbol en la escuela, doctor. Ayer en la tarde.
**Médico:** ¿Cuál tobillo?
**Paciente:** El derecho. Me caí cuando iba a patear.
**Médico:** ¿Pudiste seguir caminando después?
**Paciente:** Poquito, pero cojeando. Hoy amaneció más hinchado.
**Médico:** Del uno al diez, ¿cuánto te duele?
**Paciente:** Como un seis. Ayer me tomé un ibuprofeno que tenía mi mamá y se me quitó un rato.
**Médico:** ¿Cuántos años tienes?
**Paciente:** Catorce.
**Médico:** ¿Eres alérgica a algún medicamento?
**Paciente:** No, a ninguno.
**Paciente:** Oiga, ¿y voy a poder jugar el torneo del sábado? Es la final.
**Médico:** Ahorita lo vemos. Déjame revisarte. Inflamación en la cara lateral del tobillo derecho, con equimosis leve. Dolor a la palpación en el ligamento peroneoastragalino anterior. Sin dolor en el borde posterior del maléolo. Puedes apoyar el pie y diste cuatro pasos. Pulso pedio presente. Temperatura 36.5… no, perdón, 36.8.
**Médico:** Es un esguince. Vas a usar una venda elástica, hielo veinte minutos tres veces al día, y el pie elevado. Paracetamol de 500 cada ocho horas si te duele. Nada de deporte por dos semanas.
**Paciente:** ¿Dos semanas? Ay, no…
**Médico:** Lo siento, el sábado no. Si en una semana no mejora o no puedes apoyar el pie, regresas para tomar una radiografía.
**Paciente:** Está bien. Gracias, doctor.

**Clinician recap** (added after the glasses tests, said aloud before the plan; see Early findings in the README): the clinician summarizes the history in one sentence so it reaches the transcript in the wearer's voice, e.g. "Entonces, Valeria, te torciste el tobillo derecho ayer en la tarde jugando fútbol, dolor seis de diez, tomaste ibuprofeno y te ayudó un rato, sin alergias."

### Expected facts

- **S:** 14 años; torcedura del tobillo derecho jugando fútbol, ayer por la tarde; marcha con cojera; aumento de volumen hoy; dolor 6/10; tomó ibuprofeno por su cuenta con alivio temporal (patient-reported); niega alergias a medicamentos.
- **O:** inflamación en cara lateral del tobillo derecho con equimosis leve; dolor a la palpación en ligamento peroneoastragalino anterior; sin dolor en borde posterior del maléolo; apoya el pie y da 4 pasos; pulso pedio presente; temperatura 36.8 °C.
- **A:** esguince de tobillo derecho.
- **P:** venda elástica; hielo 20 min 3 veces al día; pie elevado; paracetamol 500 mg cada 8 h si hay dolor; sin deporte 2 semanas; regresar para radiografía si no mejora en una semana o no puede apoyar el pie.

### Traps for the verifier

- **Source:** the ibuprofen was the patient's own decision; it must not appear in the Plan.
- **Citation:** the temperature is 36.8; 36.5 was corrected and must not appear.
- **Noise:** the tournament and the final stay out of the note.
- **Scope:** no sprain grade was stated and no X-ray was taken. "Esguince grado II" or "Rx negativa" is flagged 🔴.

### Recordings

| Recording | Capture | Result |
|---|---|---|
| iPhone | Phone in the middle of the table | Both voices transcribed |
| `lentes4` | Ray-Ban Meta, no recap | Patient's answers lost; lost-audio check flagged 3 unanswered questions and the missing chief complaint |
| `lentes5` | Ray-Ban Meta, with recap | 18 ✅, 1 🔴: "con gelada" papered over as "con dificultad"; playback showed the word was "cojeando" |

Recordings stay on the author's machine (`audio/` is git-ignored).
