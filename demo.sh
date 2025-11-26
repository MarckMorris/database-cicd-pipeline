#!/bin/bash
echo "Starting Database CI/CD Pipeline..."
docker-compose up -d
sleep 15
python src/cicd_pipeline.py
