#!/usr/bin/env python3
"""
EDRefCard Models Module

This module contains the core data models and configuration classes.
"""

import os
import string
import random
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin


class Config:
    """Configuration manager for EDRefCard.
    
    Handles paths for storing and retrieving binding configurations,
    including file paths and URLs for generated reference cards.
    """
    
    # Class-level configuration - can be overridden by Flask app
    _dir_root = None
    _web_root = None
    _configs_path = None
    
    @classmethod
    def setDirRoot(cls, path):
        """Set the root directory for configs (for Flask integration)."""
        cls._dir_root = Path(path).resolve()
        
    @classmethod
    def setConfigsPath(cls, path):
        """Set the explicit path to the configs directory."""
        cls._configs_path = Path(path).resolve()
    
    @classmethod
    def setWebRoot(cls, url):
        """Set the web root URL (for Flask integration)."""
        cls._web_root = url
    
    @staticmethod
    def dirRoot():
        """Get the root directory for the application."""
        if Config._dir_root is not None:
            return Config._dir_root
        return Path(os.environ.get('CONTEXT_DOCUMENT_ROOT', '..')).resolve()
    
    @staticmethod
    def configsPath():
        """Get the path to the configs directory."""
        if Config._configs_path is not None:
            return Config._configs_path
        return Config.dirRoot() / 'configs'
    
    @staticmethod    
    def webRoot():
        """Get the web root URL for generating links."""
        # Try to use Flask request context if available
        try:
            from flask import has_request_context, request
            if has_request_context():
                return request.url_root
        except ImportError:
            pass
            
        if Config._web_root is not None:
            return Config._web_root
        return urljoin(os.environ.get('SCRIPT_URI', 'https://edrefcard.info/'), '/')
    
    @staticmethod
    def newRandom():
        """Create a new Config with a random unique name."""
        config = Config(Config.randomName())
        while config.exists():
            config = Config(Config.randomName())
        return config
    
    def __init__(self, name):
        """Initialize a Config with the given name.
        
        Args:
            name: The configuration identifier (6 lowercase letters)
            
        Raises:
            ValueError: If name is empty
        """
        if not name:
            raise ValueError('Config must have a name')
        self.name = name
    
    def __repr__(self):
        return "Config('%s')" % self.name
    
    @staticmethod
    def randomName():
        """Generate a random 6-character lowercase name."""
        name = ''.join(random.choice(string.ascii_lowercase) for x in range(6))
        return name
    

        
    def path(self):
        """Get the base path for this config's files."""
        path = Config.configsPath() / self.name[:2] / self.name
        return path
    
    def pathWithNameAndSuffix(self, name, suffix):
        """Get a path with an additional name component and suffix.
        
        Args:
            name: Additional name component (e.g., device template name)
            suffix: File suffix (must start with '.')
            
        Returns:
            Path object for the file
        """
        newName = '-'.join([self.name, name])
        p = self.path().with_name(newName)
        return p.with_suffix(suffix)
    
    def pathWithSuffix(self, suffix):
        """Get the path with the given file suffix.
        
        Args:
            suffix: File suffix (must start with '.')
            
        Returns:
            Path object for the file
        """
        return self.path().with_suffix(suffix)
        
    def exists(self):
        """Check if this config already exists on disk.

        The bare base path is never created (only suffixed files like
        <id>.binds are), so probe the .binds file too: otherwise same-named
        uploads silently reuse the run id, overwrite the previous config and
        the browser serves stale cached card images.
        """
        return self.path().exists() or self.pathWithSuffix('.binds').exists()
        
    def makeDir(self):
        """Create the directory structure for this config."""
        fullPath = self.path()
        dirPath = fullPath.parent
        dirPath.mkdir(parents=True, exist_ok=True)
        
    def refcardURL(self):
        """Get the URL to view this reference card."""
        url = urljoin(Config.webRoot(), "binds/%s" % self.name)
        return url
        
    def bindsURL(self):
        """Get the URL to download the binds file."""
        url = urljoin(Config.webRoot(), "configs/%s.binds" % self.name)
        return url


class Mode(Enum):
    """Operating modes for the application."""
    invalid = 0
    blocks = 1
    list = 2
    replay = 3
    generate = 4
    listDevices = 5


class Errors:
    """Container for error and warning messages during processing."""
    
    def __init__(
            self,
            unhandledDevicesWarnings='',
            deviceWarnings='',
            misconfigurationWarnings='',
            errors=''
        ):
        """Initialize error container.
        
        Args:
            unhandledDevicesWarnings: Warning about unsupported devices
            deviceWarnings: Warnings about specific device issues
            misconfigurationWarnings: Warnings about misconfigured controls
            errors: Critical errors that prevent processing
        """
        self.unhandledDevicesWarnings = unhandledDevicesWarnings
        self.deviceWarnings = deviceWarnings
        self.misconfigurationWarnings = misconfigurationWarnings
        self.errors = errors
    
    def __repr__(self):
        return ("Errors(unhandledDevicesWarnings='%s', deviceWarnings='%s', "
                "misconfigurationWarnings='%s', errors='%s')" 
                % (self.unhandledDevicesWarnings, self.deviceWarnings, 
                   self.misconfigurationWarnings, self.errors))
    
    def hasErrors(self):
        """Check if there are any critical errors."""
        return bool(self.errors)
    
    def hasWarnings(self):
        """Check if there are any warnings."""
        return bool(self.unhandledDevicesWarnings or 
                    self.deviceWarnings or 
                    self.misconfigurationWarnings)
