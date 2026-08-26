Apache-2.0 Notices — APA sandbox profiles
==========================================

This directory contains macOS Seatbelt policy files adapted from the
OpenAI Codex project:

  Source : https://github.com/openai/codex (codex-rs/sandboxing/src/)
  Files  : seatbelt_base_policy.sbpl,
           restricted_read_only_platform_defaults.sbpl
  License: Apache License 2.0 — Copyright 2025 OpenAI

Modifications by APA (2026): trimmed to a single code-execution policy;
workspace/tmp write carve-outs; network denied via deny-default.

Licensed under the Apache License, Version 2.0. You may obtain a copy at
http://www.apache.org/licenses/LICENSE-2.0
