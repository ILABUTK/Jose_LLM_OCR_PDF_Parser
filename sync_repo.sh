#!/bin/bash

# Source and destination directories for the copy
DEST_DIR_FROM="/home/recoil/shared_space/parserBibliographyJT/"
# Destination directory for the user "jose"
DEST_DIR_TO="/home/jose/Jose_LLM_OCR_PDF_Parser/"


# Step 2: Copy all files from EV_charging_demand_prediction to the user's folder

sudo rsync -avh --progress --update "$DEST_DIR_FROM" "$DEST_DIR_TO"


# Step 1: Change ownership of all files in EV_charging_demand_prediction to the user "jose"
sudo chown -R "jose:jose" "$DEST_DIR_TO"

