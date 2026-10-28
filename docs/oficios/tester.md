# Oficio de tester — urbanbot / hackathon

Cómo probar cada tipo de cambio. Los comandos se corren desde la raíz del
repo, con `AWS_PROFILE=hackathon-agentic` y `AWS_REGION=us-east-1` cuando
hablan con AWS. El script de humo **nunca** envía WhatsApp a un número real:
inyecta un evento SNS con un remitente ficticio (`5215599900001`).

La respuesta saliente aún no se manda por WhatsApp. Con
`SIMULATE_WHATSAPP_REPLY=1` el agente deja un log estructurado
`WOULD_SEND_REPLY` (destino enmascarado y texto) que el humo verifica.

Contraseña del portal: leerla dentro del script o del navegador con

```bash
security find-generic-password -a hackathon-portal -s firstmate-hackathon-portal -w
```

Nunca imprimirla, ni guardarla en logs, capturas o commits.

| Tipo de cambio | Cómo se prueba | Comando |
| --- | --- | --- |
| Agente (Strands / Bedrock / reply) | Unit tests del consumer y del outbound simulado; humo hasta el agente (log `agent_invoked` + `WOULD_SEND_REPLY`). Los pasos del agente pueden fallar mientras main no aplique el zip nuevo. | `python3 -m unittest discover -s modules/agent/tests` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta agente` |
| Tools Lambda (`create_report`, `join_incident`, `get_status`, `register_place`, `route`, `escalate`) | Unit tests del módulo agent (el consumer invoca al agente y el agente a las tools). Un reporte real se confirma en DynamoDB `cdshack-urbanbot-dev-reports` / `-incidents` o con el humo hasta portal. | `python3 -m unittest discover -s modules/agent/tests` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta portal` |
| Terraform (módulos / `envs/dev`) | Formato, validate local (sin backend) y `terraform test` del módulo data. El plan vive en CI; no disparar apply de main desde una rama. | `terraform fmt -check -recursive` <br> `cd envs/dev && terraform init -backend=false && terraform validate` <br> `cd modules/data && terraform test` |
| Portal y roles (Cognito admin / supervisor / operador) | Tests del dashboard; humo hasta portal (el incidente, si el agente lo creó, debe existir en la tabla que sirve AppSync). Login manual: usuario de `envs/dev/terraform.tfvars`, contraseña solo por el Llavero. | `cd apps/dashboard && npm test -- --watch=false` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta portal` |
| Canal WhatsApp (ingesta EUM → SQS → consumidor) | Unit tests de la ingesta (sobre el envelope EUM) y humo que publica en `cdshack-urbanbot-dev-inbound` y espera el log `enqueued` con el `wamid` inyectado. | `python3 -m unittest discover -s modules/compute/tests` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta ingesta` |

## Humo contra dev

```bash
AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta ingesta
AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta consumidor
AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta agente
AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta portal
```

`--hasta` corta en ese paso. Cada paso imprime `pasa` o `falla`; el proceso
sale distinto de cero al primer fallo. El techo total es 300 s (dentro del
script).

Orden: ingesta (`enqueued`) → consumidor (`agent_invoked`) → agente
(DynamoDB + `WOULD_SEND_REPLY`) → portal (incidente en
`cdshack-urbanbot-dev-incidents` cuando el agente lo crea).
