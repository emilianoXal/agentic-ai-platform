# Oficio de tester — urbanbot / hackathon

Cómo probar cada tipo de cambio. Los comandos se corren desde la raíz del
repo, con `AWS_PROFILE=hackathon-agentic` y `AWS_REGION=us-east-1` cuando
hablan con AWS. El script de humo **nunca** envía WhatsApp a un número real:
inyecta un evento SNS con un remitente ficticio (`5215599900001`).

La respuesta saliente aún no se manda por WhatsApp. Con
`SIMULATE_WHATSAPP_REPLY=1`, y solo si el remitente es el número de humo
(`SMOKE_TEST_NUMBER`, default `5215599900001`), el agente deja un log
estructurado `WOULD_SEND_REPLY` con `message_id`, destino enmascarado,
`text_len` y `text_hash`; nunca el texto. Un ciudadano real no pasa por ahí.
El humo lo verifica por `message_id` y `text_len`.

Contraseña del portal: leerla dentro del script o del navegador con

```bash
security find-generic-password -a hackathon-portal -s firstmate-hackathon-portal -w
```

Nunca imprimirla, ni guardarla en logs, capturas o commits.

| Tipo de cambio | Cómo se prueba | Comando |
| --- | --- | --- |
| Agente (Strands / Bedrock / reply) | Unit tests del consumer y del outbound simulado; humo hasta el agente (log `agent_invoked` + `WOULD_SEND_REPLY`). Los pasos del agente pueden fallar mientras main no aplique el zip nuevo. | `python3 -m unittest discover -s modules/agent/tests` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta agente` |
| Tools Lambda (`create_report`, `join_incident`, `get_status`, `register_place`, `route`, `escalate`, `delete_my_data`) | Unit tests del módulo agent (el consumer invoca al agente y el agente a las tools). Un reporte real se confirma en DynamoDB `cdshack-urbanbot-dev-reports` / `-incidents` o con el humo hasta portal. | `python3 -m pytest -q modules/agent/tests` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta portal` |
| Terraform (módulos / `envs/dev`) | Formato, validate local (sin backend) y `terraform test` del módulo data. El plan vive en CI; no disparar apply de main desde una rama. | `terraform fmt -check -recursive` <br> `cd envs/dev && terraform init -backend=false && terraform validate` <br> `cd modules/data && terraform test` |
| Portal y roles (Cognito admin / supervisor / operador) | Tests del dashboard; humo hasta portal (el incidente, si el agente lo creó, debe existir en la tabla que sirve AppSync). Login manual: usuario de `envs/dev/terraform.tfvars`, contraseña solo por el Llavero. | `cd apps/dashboard && npm test -- --watch=false` <br> `AWS_PROFILE=hackathon-agentic AWS_REGION=us-east-1 python3 scripts/smoke_whatsapp.py --hasta portal` |
| Canal WhatsApp (ingesta EUM → SQS → consumidor) | Unit tests de la ingesta; humo `--local` (mismo envelope EUM, handler del repo, sin AWS); contra dev, job manual `smoke:whatsapp` (OIDC de despliegue) o el script con perfil que pueda `SNS:Publish`. | `python3 -m unittest discover -s modules/compute/tests` <br> `python3 scripts/smoke_whatsapp.py --local --hasta ingesta` <br> job GitLab `smoke:whatsapp` (variable `SMOKE_HASTA`, default `ingesta`) |

## Humo local (sin AWS)

```bash
python3 scripts/smoke_whatsapp.py --local --hasta ingesta
```

Arma el envelope de End User Messaging Social y lo pasa por
`modules/compute/src/ingest/handler.py` en proceso, con clientes simulados.
Comprueba que el mensaje encolado lleva el remitente ficticio y el texto.

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
(`WOULD_SEND_REPLY` con el `message_id` y `text_len` > 0) → portal
(incidente en `cdshack-urbanbot-dev-incidents` de un reporte del remitente
ficticio creado en esta corrida, cuando el agente lo crea).

## Borrado de datos personales

Antes de `apply`, ejecutar `python3 -m pytest -q modules/agent/tests -k delete`.
La prueba usa DynamoDB simulado y comprueba confirmación obligatoria, que el
sujeto es siempre el remitente del evento, que sin `AGENTCORE_MEMORY_ID` no se
borra nada, eliminación de usuario y lugares, baja de `incidents.subscribers`,
anonimización de reportes, conservación del conteo del incidente e idempotencia,
además del borrado de AgentCore Memory y su fallo seguro (`memory_erasure_failed`).
El borrado requiere AgentCore Memory habilitada (lo está en dev); sin ella la
herramienta responde `deletion_unavailable`. Con Memory, usar el job manual
`agent:conversations` con el número ficticio: solicitar el borrado, comprobar
que el agente pide responder `CONFIRMO BORRAR MIS DATOS` y enviarlo en un
segundo mensaje. Verificar en DynamoDB que no quede el número ficticio en users,
places, reports ni en `subscribers` de incidents y que el incidente conserve su
`report_count`; el audit log solo debe contener el hash y, tras un mensaje
nuevo, el agente no debe recordar la conversación anterior al borrado.

Para el historial DynamoDB, instalar las dependencias de prueba con
`python3 -m pip install boto3 pytest 'moto[dynamodb,secretsmanager]'` y ejecutar
`python3 -m pytest -q modules/agent/tests/test_conversation_history.py`.
Los planes simulados del contrato de almacenamiento se ejecutan con
`terraform -chdir=modules/data test -filter=tests/conversation_history.tftest.hcl`
y `terraform -chdir=modules/agent test -filter=tests/conversation_history.tftest.hcl`
después de inicializar los módulos con `init -backend=false`.
Después del apply autorizado de main, enviar dos turnos del mismo ciudadano
(por ejemplo descripción y luego ubicación), y comprobar `history_loaded` con
`turns` mayor que cero en el segundo turno. El registro contiene solo la clave
HMAC y el conteo; el texto de la conversación no debe aparecer en CloudWatch.
