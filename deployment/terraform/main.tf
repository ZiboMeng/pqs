resource "terraform_data" "phase3_deployment_contract" {
  input = {
    image_digest              = var.image_digest
    replicas                  = var.replicas
    run_as_user               = var.run_as_user
    read_only_root_filesystem = var.read_only_root_filesystem
    persistent_volume_encrypted = var.persistent_volume_encrypted
    live_enabled              = var.live_enabled
    broker_write_enabled      = var.broker_write_enabled
  }

  lifecycle {
    precondition {
      condition = (
        var.replicas == 1 &&
        var.run_as_user == 10001 &&
        var.read_only_root_filesystem &&
        var.persistent_volume_encrypted &&
        !var.live_enabled &&
        !var.broker_write_enabled
      )
      error_message = "Phase 3 singleton/PAPER/least-privilege contract failed."
    }
  }
}
