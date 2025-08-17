#!/bin/bash

# M4 Supra Sound System Installation Script
# This script sets up the systemd service for auto-startup

echo "M4 Supra Sound System - Service Installation"
echo "============================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script as root (use sudo)"
    exit 1
fi

# Variables
SERVICE_NAME="m4-supra-sound"
SERVICE_FILE="${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="/home/pi/M4HCSUP"
SYSTEMD_DIR="/etc/systemd/system"

echo "Current directory: $SCRIPT_DIR"
echo "Target directory: $TARGET_DIR"

# Create target directory if it doesn't exist
if [ ! -d "$TARGET_DIR" ]; then
    echo "Creating target directory: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
    chown pi:pi "$TARGET_DIR"
fi

# Copy files to target directory
echo "Copying Python script to $TARGET_DIR"
cp "$SCRIPT_DIR/m4_supra_v2.py" "$TARGET_DIR/"
chown pi:pi "$TARGET_DIR/m4_supra_v2.py"
chmod +x "$TARGET_DIR/m4_supra_v2.py"

# Copy sound directories
echo "Copying sound directories..."
if [ -d "$SCRIPT_DIR/m4" ]; then
    cp -r "$SCRIPT_DIR/m4" "$TARGET_DIR/"
    chown -R pi:pi "$TARGET_DIR/m4"
fi

if [ -d "$SCRIPT_DIR/supra" ]; then
    cp -r "$SCRIPT_DIR/supra" "$TARGET_DIR/"
    chown -R pi:pi "$TARGET_DIR/supra"
fi

# Update service file paths and copy to systemd
echo "Installing systemd service..."
sed "s|/home/pi/M4HCSUP|$TARGET_DIR|g" "$SCRIPT_DIR/$SERVICE_FILE" > "$SYSTEMD_DIR/$SERVICE_FILE"

# Reload systemd and enable the service
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling $SERVICE_NAME service..."
systemctl enable "$SERVICE_NAME"

echo ""
echo "Installation complete!"
echo ""
echo "Service commands:"
echo "  Start:   sudo systemctl start $SERVICE_NAME"
echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
echo "  Status:  sudo systemctl status $SERVICE_NAME"
echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "The service will automatically start on boot."
echo "You can start it now with: sudo systemctl start $SERVICE_NAME"