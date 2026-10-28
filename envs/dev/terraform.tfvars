environment          = "dev"
media_retention_days = 30

# Dashboard staff (Cognito e-mails each a temporary password on creation).
# Every team member gets the three roles: admin on their own address, and an
# agency operator (Organismo de Agua) and a municipal supervisor on +aliases.
staff_users = {
  "emiliano.obregon@xaldigital.com"            = { name = "Emiliano Obregón", group = "admin" }
  "emiliano.obregon+agua@xaldigital.com"       = { name = "Emiliano Obregón (Operador Organismo de Agua)", group = "agency", agency_id = "organismo-de-agua" }
  "emiliano.obregon+supervisor@xaldigital.com" = { name = "Emiliano Obregón (Supervisor municipal)", group = "official" }
  "antonio.miguel@xaldigital.com"              = { name = "Antonio Miguel", group = "admin" }
  "antonio.miguel+agua@xaldigital.com"         = { name = "Antonio Miguel (Operador Organismo de Agua)", group = "agency", agency_id = "organismo-de-agua" }
  "antonio.miguel+supervisor@xaldigital.com"   = { name = "Antonio Miguel (Supervisor municipal)", group = "official" }
  "karla.segura@xaldigital.com"                = { name = "Karla Segura", group = "admin" }
  "karla.segura+agua@xaldigital.com"           = { name = "Karla Segura (Operador Organismo de Agua)", group = "agency", agency_id = "organismo-de-agua" }
  "karla.segura+supervisor@xaldigital.com"     = { name = "Karla Segura (Supervisor municipal)", group = "official" }
  "josue.jimenez@xaldigital.com"               = { name = "Josué Jiménez", group = "admin" }
  "josue.jimenez+agua@xaldigital.com"          = { name = "Josué Jiménez (Operador Organismo de Agua)", group = "agency", agency_id = "organismo-de-agua" }
  "josue.jimenez+supervisor@xaldigital.com"    = { name = "Josué Jiménez (Supervisor municipal)", group = "official" }
}
