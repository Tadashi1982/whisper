import os

import yaml


class ConfigManager:
    _instance = None

    def __init__(self):
        """Initialize the ConfigManager instance."""
        self.config = None
        self.schema = None

    @classmethod
    def initialize(cls, schema_path=None):
        """Initialize the ConfigManager with the given schema path."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.schema = cls._instance.load_config_schema(schema_path)
            cls._instance.config = cls._instance.load_default_config()
            cls._instance.load_user_config()

    @classmethod
    def get_schema(cls):
        """Get the configuration schema."""
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")
        return cls._instance.schema

    @classmethod
    def get_config_section(cls, *keys):
        """Get a specific section of the configuration."""
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")

        section = cls._instance.config
        for key in keys:
            if isinstance(section, dict) and key in section:
                section = section[key]
            else:
                return {}
        return section

    @classmethod
    def get_config_value(cls, *keys):
        """Get a specific configuration value using nested keys."""
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")

        value = cls._instance.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    @classmethod
    def set_config_value(cls, value, *keys):
        """Set a specific configuration value using nested keys."""
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")

        config = cls._instance.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            elif not isinstance(config[key], dict):
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value

    @staticmethod
    def load_config_schema(schema_path=None):
        """Load the configuration schema from a YAML file."""
        if schema_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            schema_path = os.path.join(base_dir, 'config_schema.yaml')

        with open(schema_path) as file:
            schema = yaml.safe_load(file)
        return schema

    def load_default_config(self):
        """Load default configuration values from the schema."""
        def extract_value(item):
            if isinstance(item, dict):
                if 'value' in item:
                    return item['value']
                else:
                    return {k: extract_value(v) for k, v in item.items()}
            return item

        config = {}
        for category, settings in self.schema.items():
            config[category] = extract_value(settings)
        return config

    def load_user_config(self, config_path=None):
        """Load user configuration and merge with default config, validating
        each value against the schema (type + options)."""
        from paths import user_config_path
        if config_path is None:
            config_path = user_config_path()

        if config_path and os.path.isfile(config_path):
            try:
                with open(config_path) as file:
                    user_config = yaml.safe_load(file) or {}
            except yaml.YAMLError:
                print("Error in configuration file. Using default configuration.")
                return
            self._validated_update(self.config, user_config, self.schema, path='')

    @staticmethod
    def _coerce(value, declared_type):
        """Try to coerce loaded YAML value to declared type. Returns
        (coerced_value, ok) where ok is False on type mismatch."""
        if value is None:
            return None, True
        type_map = {
            'bool': bool,
            'int': int,
            'float': (int, float),
            'str': str,
        }
        expected = type_map.get(declared_type)
        if expected is None:
            return value, True
        if isinstance(value, expected):
            return (float(value) if declared_type == 'float' and isinstance(value, int) else value), True
        return value, False

    def _validated_update(self, target, overrides, schema_node, path):
        """Recursively merge overrides into target, checking each leaf
        against schema_node. Logs warnings for unknown keys, type mismatches
        and out-of-options values, then keeps the existing default."""
        if not isinstance(overrides, dict):
            return
        for key, value in overrides.items():
            keypath = f'{path}.{key}' if path else key
            sub_schema = schema_node.get(key) if isinstance(schema_node, dict) else None
            if sub_schema is None:
                print(f'[config] Unknown key {keypath!r}; ignored.')
                continue
            if isinstance(sub_schema, dict) and 'value' in sub_schema:
                declared_type = sub_schema.get('type')
                options = sub_schema.get('options')
                coerced, ok = self._coerce(value, declared_type)
                if not ok:
                    print(f'[config] {keypath!r}: expected {declared_type}, got {type(value).__name__}; using default.')
                    continue
                if options is not None and coerced is not None and coerced not in options:
                    print(f'[config] {keypath!r}: value {coerced!r} not in {options}; using default.')
                    continue
                target[key] = coerced
            elif isinstance(value, dict):
                if not isinstance(target.get(key), dict):
                    target[key] = {}
                self._validated_update(target[key], value, sub_schema, keypath)
            else:
                print(f'[config] {keypath!r}: schema expects a section, got scalar; ignored.')

    @classmethod
    def save_config(cls, config_path=None):
        """Save the current configuration to a YAML file."""
        from paths import user_config_path
        if config_path is None:
            config_path = user_config_path()
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")
        with open(config_path, 'w') as file:
            yaml.dump(cls._instance.config, file, default_flow_style=False)

    @classmethod
    def reload_config(cls):
        """
        Reload the configuration from the file.
        """
        if cls._instance is None:
            raise RuntimeError("ConfigManager not initialized")
        cls._instance.config = cls._instance.load_default_config()
        cls._instance.load_user_config()

    @classmethod
    def config_file_exists(cls):
        """Check if a valid config file exists."""
        from paths import user_config_path
        return os.path.isfile(user_config_path())

    @classmethod
    def console_print(cls, message):
        """Print a message to the console if enabled in the configuration."""
        if cls._instance and cls._instance.config['misc']['print_to_terminal']:
            print(message)
