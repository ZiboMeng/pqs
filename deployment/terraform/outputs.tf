output "validated_phase3_contract" {
  description = "Validated inputs for a platform-specific deployment module."
  value       = terraform_data.phase3_deployment_contract.output
}
