environment                 = "dev"
media_retention_days        = 1
enable_agentcore_memory     = false
enable_conversation_history = true

# WhatsApp phone-number id the notifier sends proactive notifications FROM
# (status changes, nearby incidents). Without it the notifier skips every
# proactive send ("skipped_no_origination"), so citizens never get status
# updates even though the portal publishes StatusChanged correctly. Conversational
# replies don't need this (they reuse the inbound message's origination id).
outbound_origination_phone_number_id = "arn:aws:social-messaging:us-east-1:636487155766:phone-number-id/e644d37f4dab45d5a57a5676effc9956"

dependency_email_map = {
  agua      = "antonio.miguel+agua@xaldigital.com"
  alumbrado = "emiliano.obregon+luz@xaldigital.com"
  bacheo    = "karla.segura+baches@xaldigital.com"
  basura    = "josue.jimenez+basura@xaldigital.com"
  drenaje   = "antonio.miguel+agua@xaldigital.com"
  arbol     = "emiliano.obregon+luz@xaldigital.com"
  plagas    = "emiliano.obregon+luz@xaldigital.com"
}
dependency_fallback_email = "antonio.miguel+supervisor@xaldigital.com"
dependency_mail_from      = "antonio.miguel@xaldigital.com"

# Dashboard staff (Cognito e-mails each a temporary password on creation).
# Every team member gets the three roles: admin on their own address, an agency
# operator on +<area> (a different agency per person) and a municipal supervisor
# on +supervisor.
staff_users = {
  "emiliano.obregon@xaldigital.com"            = { name = "Emiliano Obregón", group = "admin" }
  "emiliano.obregon+luz@xaldigital.com"        = { name = "Emiliano Obregón (Operador Servicios Publicos)", group = "agency", agency_id = "servicios-publicos" }
  "emiliano.obregon+supervisor@xaldigital.com" = { name = "Emiliano Obregón (Supervisor municipal)", group = "official" }
  "antonio.miguel@xaldigital.com"              = { name = "Antonio Miguel", group = "admin" }
  "antonio.miguel+agua@xaldigital.com"         = { name = "Antonio Miguel (Operador Organismo de Agua)", group = "agency", agency_id = "organismo-de-agua" }
  "antonio.miguel+supervisor@xaldigital.com"   = { name = "Antonio Miguel (Supervisor municipal)", group = "official" }
  "karla.segura@xaldigital.com"                = { name = "Karla Segura", group = "admin" }
  "karla.segura+baches@xaldigital.com"         = { name = "Karla Segura (Operador Obras Publicas)", group = "agency", agency_id = "obras-publicas" }
  "karla.segura+supervisor@xaldigital.com"     = { name = "Karla Segura (Supervisor municipal)", group = "official" }
  "josue.jimenez@xaldigital.com"               = { name = "Josué Jiménez", group = "admin" }
  "josue.jimenez+basura@xaldigital.com"        = { name = "Josué Jiménez (Operador Limpia Publica)", group = "agency", agency_id = "limpia-publica" }
  "josue.jimenez+supervisor@xaldigital.com"    = { name = "Josué Jiménez (Supervisor municipal)", group = "official" }
}
