#!/bin/bash
python3 -m venv cloud
source cloud/bin/activate
cloud/bin/pip install -r requirements.txt --break-system-packages