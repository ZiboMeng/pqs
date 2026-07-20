variable "image_digest" {
  description = "Signed immutable OCI image reference, including @sha256:<64 hex>."
  type        = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest must be an immutable sha256 OCI reference."
  }
}

variable "replicas" {
  type    = number
  default = 1
  validation {
    condition     = var.replicas == 1
    error_message = "Phase 3 local SQLite authority requires exactly one replica."
  }
}

variable "run_as_user" {
  type    = number
  default = 10001
  validation {
    condition     = var.run_as_user == 10001
    error_message = "The certified image runs as uid 10001."
  }
}

variable "read_only_root_filesystem" {
  type    = bool
  default = true
  validation {
    condition     = var.read_only_root_filesystem
    error_message = "The root filesystem must remain read-only."
  }
}

variable "persistent_volume_encrypted" {
  type    = bool
  default = true
  validation {
    condition     = var.persistent_volume_encrypted
    error_message = "The state volume must be encrypted by the target platform."
  }
}

variable "live_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.live_enabled
    error_message = "Phase 3 cannot enable LIVE."
  }
}

variable "broker_write_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.broker_write_enabled
    error_message = "Phase 3 cannot enable external broker writes."
  }
}
