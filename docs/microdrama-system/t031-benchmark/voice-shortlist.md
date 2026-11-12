# T031 benchmark: Botnoi voice shortlist and the 4 clips to make (12 Nov 2026)

> **Superseded the same day:** Studio has no usable emotion control (operator), so the benchmark uses
> **two neutral clips only** (`A-NEUTRAL.wav`, `B-NEUTRAL.wav`). The prompt carries S05's grief and S06's
> anger. See DECISIONS "D2 revised again" and `voices-manifest.json`.

Speaker **A** is a man, about 30 (S01, S03–S05, S07, S08; grief in S05). Speaker **B** is "May", a
woman, about 28 (S02–S04, S06; restrained anger in S06). The clips are the Pika Ref2VA **voice
references**, one per (speaker, emotion) the matrix uses.

## Shortlist

Drawn from the 11 Nov API snapshot (`v3-workflow/botnoi-api-speakers-2026-11-11.csv`). Filter: Thai,
Adult, no regional accent, Botnoi's own voices (no `ctb` sample files), not teaching/selling styles.
The API serves only V1/V2, so **confirm V4 in Studio** for your pick. A Studio-only Botnoi Cast voice
that fits better is fine; tell me its name.

| For | Voice (API id) | Thai name | Style | V2 also listed | Sample |
|-----|----------------|-----------|-------|----------------|--------|
| A | Nick (56) | นิค | Confident; storytelling | yes (37) | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/nick/sound_1_nick.wav) |
| A | tee (39) | ตี๋ | Confident; storytelling | yes (76) | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/tee/sound_tee.wav) |
| A | Toto (30) | โตโต้ | Soothing; storytelling | yes (78) | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/toto/sound_toABO5.wav) |
| A | Max (4) | แม็กซ์ | Trustworthy; storytelling | no | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/max/sound_max.wav) |
| B | Ngam (3) | คุณงาม | Confident; storytelling | yes (65) | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/ngam/sound_ngam.wav) |
| B | meow (42) | เหมียว | Confident; storytelling | yes (60) | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/meow/sound_meow.wav) |
| B | Lynn (160) | ริณณ์ | Confident; storytelling | no | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/lynn/sound_lynn.wav) |
| B | Daonapha (162) | ดาวนภา | Calm; storytelling | no | [listen](https://botnoi-voice.s3.ap-southeast-1.amazonaws.com/picture/daonapha/sound_daonapha.wav) |

Pick A and B so they are **easy to tell apart**, because the benchmark checks for swapped voices.

## The 4 clips (Studio, V4, about 10–15 seconds each)

The anchor text is deliberately **not** a benchmark line, so the model can't copy the reference audio
into a shot. If Studio's V4 has an emotion or style control, use it for SAD and ANGRY. If not, read the
emotion in the voice's own style. Have the Thai listener check the text and delivery.

| File name | Speaker / emotion | Text |
|-----------|-------------------|------|
| `A-NEUTRAL.wav` | A, neutral | วันนี้อากาศดีมาก ผมเลยตั้งใจว่าจะเดินไปทำงาน แล้วแวะกินกาแฟที่ร้านหัวมุมถนนก่อนเข้าออฟฟิศ |
| `A-SAD.wav` | A, restrained grief | ผมยังจำวันที่เราย้ายออกจากบ้านหลังเก่าได้ดี ทุกอย่างเงียบไปหมด แล้วผมก็ไม่รู้จะพูดอะไรเลย |
| `B-NEUTRAL.wav` | B, neutral | เมื่อวานฉันกลับบ้านดึก เพราะต้องประชุมกับลูกค้าจนเกือบสามทุ่ม แต่ก็คุ้มค่า เพราะงานผ่านไปได้ด้วยดี |
| `B-ANGRY.wav` | B, restrained anger, no shouting | ฉันบอกไปแล้วหลายครั้งว่าอย่าทำแบบนี้ แต่ก็ยังทำอีก ครั้งนี้ฉันจะไม่ยอมเงียบแล้ว |

English meanings:
- A-NEUTRAL: "The weather is lovely today, so I decided to walk to work and stop for coffee at the corner
  shop before the office."
- A-SAD: "I still remember the day we moved out of the old house. Everything went quiet, and I didn't
  know what to say."
- B-NEUTRAL: "I got home late yesterday because I had a client meeting until almost nine, but it was worth
  it, because it went well."
- B-ANGRY: "I've said many times not to do this, and it happened again. This time I won't stay quiet."

**Where to put them:** `/root/AIVORA/media/samples/drama-box-t031-refs/voices/`. Drag them in through
VS Code. Use the best export quality Studio offers (WAV if it can). The orchestrator records each
file's sha256, voice id, V4 confirmation and rights basis (`OPERATOR_ATTESTED`, O-11) at sign-off.
