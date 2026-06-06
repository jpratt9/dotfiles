#!/bin/bash
# Launch Chrome with MV2 disablement turned OFF so the original uBlock Origin
# still loads (Google killed MV2 in stable Chrome ~Oct 2024; this flag opts
# the local browser out of the feature flag that removes MV2 extensions).
# Pulled from the "Google Chrome with uBlock" Automator app I made.

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --disable-features=ExtensionManifestV2Unsupported,ExtensionManifestV2Disabled
