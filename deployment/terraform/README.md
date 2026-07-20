# Phase 3 OpenTofu/Terraform contract module

This module validates the immutable image, singleton, non-root, read-only-root,
encrypted-volume, PAPER-only and no-broker-write inputs. It intentionally creates
no cloud resources and requires no cloud provider credentials. Feed its validated
output into a separately reviewed platform module only after explicit user
authorization. Applying this module alone does not deploy PQS.
