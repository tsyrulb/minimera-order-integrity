# Third-party models and services

The MIT license applies to the original application source and fixtures. It does not relicense model weights or third-party services. This repository does not distribute model weights.

## Order Integrity integrations

The current Order Integrity application uses `openai.gpt-oss-120b-1:0` through Amazon Bedrock. The judge simulation replays actual recorded answers; fresh inference requires explicit local configuration and the operator's AWS credentials. The separately identified Context Lab experiments below remain historical evidence.

AG Studio 3.1.0 and `ag-studio-react` 3.1.0 are commercial dependencies; the installed packages identify their licence as `Commercial`. Their terms remain separate from the MIT licence for Minimera's original code. The entrant's local Pro + AI trial key is excluded from source packages. A source build without that key uses vendor evaluation diagnostics. See [the actual integration and evaluation scope](docs/ORDER_INTEGRITY.md#ag-studio-trial-licence) and [AG Studio's official licence page](https://www.ag-grid.com/studio/react/enterprise-licence/). No vendor dependencies or model weights are relicensed by this project.

The demo video uses generic synthetic English narration generated locally with Piper 1.8.0 and the `en_US-ljspeech-high` voice. Voice-model revision and hashes are retained with the local video. The [voice model card](https://huggingface.co/rhasspy/piper-voices/blob/cf910fb59f1d79ab3b625a63993a108751c6c25d/en/en_US/ljspeech/high/MODEL_CARD) identifies the [public-domain LJ Speech dataset](https://keithito.com/LJ-Speech-Dataset/); the voice repository includes its MIT licence. The [Piper engine](https://github.com/OHF-Voice/piper1-gpl) is a separate development tool, not distributed with this source package. No music or model weights are included in the video.

## Current Bedrock model

The current `gpt-oss120b-routing-v21-20261105` experiment uses `openai.gpt-oss-120b-1:0` through Amazon Bedrock in `us-east-1`. OpenAI's [official model documentation](https://developers.openai.com/api/docs/models/gpt-oss-120b) identifies the Apache 2.0 model license. [AWS documents its Bedrock endpoints and features](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-oss-120b.html). This app uses the AWS credential chain, not an OpenAI API account. Service use remains subject to AWS terms and model access. No weights are redistributed.

All 90 planned observations are preserved, including one invalid full-context response. The purpose-specific mode passes the fixed synthetic gates; this does not establish production or legal readiness. Provider reasoning content is excluded from persisted results. Development-only Qwen candidates and the previous experiments remain as provenance.

## Earlier Bedrock model

The separately recorded `qwen3-next-bedrock-20261104` experiment uses Amazon Bedrock's `qwen.qwen3-next-80b-a3b` in `us-east-1`. AWS's [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-qwen-qwen3-next-80b-a3b.html) links to the [Qwen3-Next-80B-A3B-Instruct Apache 2.0 license](https://huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct/blob/main/LICENSE). Bedrock service use remains subject to the operator's AWS terms and model access. No weights or AWS credentials are distributed.

Actual Converse calls were made for all 90 planned observations. Invalid answers remain failures. The adapter also has network-free tests for signing, credential isolation, bounded responses, cancellation, the request allowance and output validation. AWS Activate's general eligibility for Bedrock does not establish that this account's particular grant covered these calls.

## Original local evaluation model

The recorded benchmark used Ollama's `qwen2.5:3b`, based on Qwen2.5-3B-Instruct. Its installed license metadata and the [upstream license](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) identify the **Qwen RESEARCH LICENSE AGREEMENT**. That agreement limits its grant to non-commercial research/evaluation and requires a separate license for commercial use.

The local work here is a research/evaluation prototype, with no paid model service or commercial deployment. Recorded outputs are retained as evaluation evidence. Do not treat this baseline as a commercially licensed production model. This repository does not establish whether a particular public hackathon demonstration fits the model license; verify the intended use or select another appropriately licensed model before the final submission. The application's model adapter can be replaced independently of the local policy and evaluation interface.

## Optional cloud model

The Responses API adapter uses the operator's own OpenAI API account, model access and applicable provider terms. It has been checked with mocked HTTP responses, not a real account key in this development run. No cloud key or provider service is supplied by the repository. Recorded Qwen results do not establish the performance of another model.

## Infrastructure and development tools

PayPal sandbox access is governed by PayPal's developer terms. Python packages, Ollama, Playwright and the optional video tooling retain their respective licenses. Native application branding and interface assets in this repository are original. The prepared demonstration contains no third-party music and does not redistribute FFmpeg binaries.

## Interface fonts

Order Integrity bundles IBM Plex Sans and IBM Plex Mono under the SIL Open Font License 1.1. Their license and copyright notice are retained in `ui/src/fonts/OFL-IBM-Plex.txt`. Font files are served by the local application; displaying the interface requires no third-party font requests.

The Minimera wordmark combines an original initial mark with outlined IBM Plex Sans lettering. The SVG files contain paths rather than a redistributed modified font.
