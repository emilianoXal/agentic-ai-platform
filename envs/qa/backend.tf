terraform {
  backend "s3" {
    # bucket intentionally OMITTED — supplied at init time via
    # -backend-config="bucket=${TF_STATE_BUCKET}" (CI/CD project variable).
    key          = "urbanbot/qa/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
