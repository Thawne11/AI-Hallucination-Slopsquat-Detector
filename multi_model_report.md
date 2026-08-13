# Multi-Model PHR/RHR Pilot

Local open-weight models, generated directly via Ollama (no manual copy-paste), following the same PHR/RHR methodology as rerun_analyze.py.

| Model | Samples | With hallucination | PHR |
|---|---|---|---|
| qwen2.5-coder:7b | 220 | 20 | 9.1% |
| llama3.2:3b | 220 | 24 | 10.9% |

## qwen2.5-coder:7b
- `js-rate-limit::rate-limit-memory`: RHR = 10%
- `py-mqtt-client::paho`: RHR = 100%
- `py-grpc-client::my_service_pb2_grpc`: RHR = 30%
- `py-grpc-client::my_service_pb2`: RHR = 20%
- `py-grpc-client::myservice_pb2`: RHR = 20%
- `py-grpc-client::myservice_pb2_grpc`: RHR = 10%
- `py-saml-parse::saml2`: RHR = 40%

## llama3.2:3b
- `js-rate-limit::rate-limiter-middleware`: RHR = 10%
- `js-rate-limit::ip2proxy`: RHR = 10%
- `js-rate-limit::ipaddr5`: RHR = 10%
- `py-mqtt-client::paho`: RHR = 100%
- `py-grpc-client::your_service`: RHR = 10%
- `py-grpc-client::channel_credentials_pb2_grpc`: RHR = 10%
- `py-grpc-client::channel_credentials_pb2`: RHR = 10%
- `py-saml-parse::saml2`: RHR = 40%
- `py-saml-parse::samllib`: RHR = 10%
- `js-grpc-client::@grpc/client`: RHR = 10%
- `js-pdf-invoice::json2htmlparser`: RHR = 10%
- `js-pdf-invoice::js2pdf`: RHR = 10%
- `js-graphql-client::@aws-sdk/client-graphql`: RHR = 10%
- `js-graphql-client::@aws-sdk/client-graph-cql`: RHR = 10%
