"""Offline checks for the documented DevFlow Postman v2.1 authoring profile.

The profile deliberately narrows valid Postman documents to reproducible local API handoffs.
It validates structure and declared coverage; the auditor establishes the actual API contract.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA = 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'
SCHEMAS = {SCHEMA, 'https://schema.postman.com/json/collection/v2.1.0/collection.json'}
VARIABLE = re.compile(r'\{\{([^{}]+)\}\}')
CREDENTIAL = re.compile(r'token|secret|password|passwd|authorization|cookie|api[-_]?key|client[-_]?key', re.I)
AUTH_TYPES = {'noauth', 'apikey', 'awsv4', 'basic', 'bearer', 'digest', 'edgegrid', 'hawk', 'oauth1', 'oauth2', 'ntlm'}


def strict_json(text: str) -> Any:
    """Reject duplicate keys and non-finite numbers so a second value cannot hide a credential."""
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError(f'duplicate JSON key: {key}')
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f'non-JSON number: {value}')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def text_description(value: Any) -> str:
    return value if isinstance(value, str) else value.get('content', '') if isinstance(value, dict) else ''


def route_key(value: str) -> str:
    """Normalize route parameters while preserving literal path segments and HTTP methods."""
    method, _, path = value.partition(' ')
    path = path.split('?', 1)[0].rstrip('/') or '/'
    path = re.sub(r'\{\{[^{}]+\}\}|\{[^{}]+\}|:[A-Za-z_][\w]*', '{}', path)
    return method.upper() + ' ' + path


def collection_errors(doc: Any, endpoints: Any, api_note: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ['Postman collection must be an object']
    info = doc.get('info')
    if not isinstance(info, dict) or not isinstance(info.get('name'), str) or not info['name'].strip():
        errors.append('Postman info.name must be nonblank')
    if not isinstance(info, dict) or info.get('schema') not in SCHEMAS:
        errors.append('Postman info.schema must identify collection v2.1.0')
    if not isinstance(api_note, str) or not api_note.strip():
        errors.append('Postman api_note must explain the branch API coverage or its N/A assessment')
    if not isinstance(endpoints, list) or any(not isinstance(e, str) or not re.fullmatch(r'[A-Z]+ /\S*', e) for e in endpoints):
        errors.append('Postman api_endpoints must be a list of METHOD /path declarations')
        endpoints = []
    elif len(endpoints) != len(set(endpoints)):
        errors.append('Postman api_endpoints contains duplicates')

    declared: set[str] = set()
    defaults: dict[str, Any] = {}
    seen_routes: set[str] = set()
    request_count = 0

    def variables(node, inherited):
        values = node.get('variable', [])
        names = set(inherited)
        local = set()
        if not isinstance(values, list):
            errors.append('Postman variable must be an array'); return names
        for entry in values:
            if not isinstance(entry, dict) or not isinstance(entry.get('key'), str) or not entry['key'].strip():
                errors.append('Postman variable entry requires a nonblank key'); continue
            key = entry['key']
            if key in local:
                errors.append(f'Postman duplicate variable: {key}')
            local.add(key); names.add(key); declared.add(key)
            value = entry.get('value', '')
            if CREDENTIAL.search(key) and value not in ('', None):
                errors.append(f'Postman credential variable must have an empty default: {key}')
            if node is doc:
                defaults[key] = value
        return names

    def events(node, inherited_tests):
        values = node.get('event', [])
        tests = inherited_tests
        if not isinstance(values, list):
            errors.append('Postman event must be an array'); return tests
        for entry in values:
            if not isinstance(entry, dict) or entry.get('listen') not in {'test', 'prerequest'}:
                errors.append('Postman event.listen must be test or prerequest'); continue
            script = entry.get('script')
            if not isinstance(script, dict):
                errors.append('Postman event.script must be an object'); continue
            source = script.get('exec')
            if isinstance(source, list) and all(isinstance(s, str) for s in source):
                source = '\n'.join(source)
            if not isinstance(source, str) or not source.strip():
                errors.append('Postman script.exec must contain executable text'); continue
            if script.get('type', 'text/javascript') != 'text/javascript':
                errors.append('Postman script.type must be text/javascript')
            if entry.get('listen') == 'test' and entry.get('disabled') is not True:
                tests = tests or ('pm.test' in source and ('pm.expect' in source or 'pm.response' in source))
        return tests

    def auth(node):
        value = node.get('auth')
        if value is None:
            return
        if not isinstance(value, dict) or value.get('type') not in AUTH_TYPES:
            errors.append('Postman auth requires a supported type'); return
        kind = value['type']
        if kind == 'noauth':
            return
        entries = value.get(kind)
        if not isinstance(entries, list) or not entries:
            errors.append(f'Postman auth.{kind} requires attribute entries'); return
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('key'), str):
                errors.append('Postman auth attribute requires a key'); continue
            val = entry.get('value', '')
            if entry['key'] in {'token', 'password', 'secret', 'accessKey', 'secretKey', 'accessToken', 'clientSecret', 'value'}:
                if val and (not isinstance(val, str) or not VARIABLE.fullmatch(val)):
                    errors.append('Postman credential auth values must be variable references')

    def scan(value, names):
        if isinstance(value, str):
            missing_names = sorted(n for n in set(VARIABLE.findall(value)) - names if not n.startswith('$'))
            if missing_names:
                errors.append('Postman undeclared variable references in scope: ' + ', '.join(missing_names))
            if re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', value):
                errors.append('Postman apparent credential/JWT literal must be removed')
        elif isinstance(value, list):
            for entry in value: scan(entry, names)
        elif isinstance(value, dict):
            # Form fields, query parameters and auth attributes encode the field name as key.
            if CREDENTIAL.search(str(value.get('key', ''))):
                field = value.get('value')
                if isinstance(field, str) and field.strip() and not VARIABLE.search(field):
                    errors.append('Postman credential field value must use an empty variable')
            for key, entry in value.items():
                if CREDENTIAL.search(str(key)) and isinstance(entry, str) and entry.strip() and not VARIABLE.search(entry):
                    errors.append(f'Postman credential field must use a variable: {key}')
                scan(entry, names)

    def visit(node, inherited_variables, inherited_tests=False):
        nonlocal request_count
        names = variables(node, inherited_variables)
        tests = events(node, inherited_tests)
        auth(node)
        scan({key: value for key, value in node.items() if key not in {'item', 'request'}}, names)
        if 'item' in node:
            if 'request' in node:
                errors.append('Postman item cannot be both a folder and a request')
            children = node['item']
            if not isinstance(children, list):
                errors.append('Postman item must be an array'); return
            for child in children:
                if not isinstance(child, dict):
                    errors.append('Postman item entry must be an object'); continue
                visit(child, names, tests)
            return
        request = node.get('request')
        if not isinstance(request, dict):
            errors.append('Postman request must be an object in the DevFlow profile'); return
        request_count += 1
        if not isinstance(node.get('name'), str) or not node['name'].strip():
            errors.append('Postman request item requires a nonblank name')
        method = request.get('method')
        if not isinstance(method, str) or not re.fullmatch(r'[A-Z]+', method):
            errors.append('Postman request.method must be an uppercase HTTP method'); method = 'GET'
        url = request.get('url')
        if isinstance(url, dict):
            url_vars = variables({'variable': url.get('variable', [])}, names)
            names = url_vars
            url = url.get('raw')
        if not isinstance(url, str) or not url.startswith('{{baseUrl}}/'):
            errors.append('Postman request.url must start with {{baseUrl}}/ and include a raw URL')
        else:
            seen_routes.add(route_key(method + ' ' + url[len('{{baseUrl}}'):]))
        headers = request.get('header', [])
        if not isinstance(headers, list):
            errors.append('Postman request.header must be an array')
        else:
            for header in headers:
                if not isinstance(header, dict) or not isinstance(header.get('key'), str) or not isinstance(header.get('value'), str):
                    errors.append('Postman header requires string key and value'); continue
                if CREDENTIAL.search(header['key']) and header['value'] and not VARIABLE.search(header['value']):
                    errors.append(f'Postman credential header must use a variable: {header["key"]}')
        auth(request)
        scan(request, names)
        body = request.get('body')
        if body is not None:
            if not isinstance(body, dict) or body.get('mode') not in {'raw', 'urlencoded', 'formdata', 'graphql', 'file'}:
                errors.append('Postman request.body requires a supported mode')
            else:
                mode = body['mode']; value = body.get(mode)
                expected = str if mode == 'raw' else list if mode in {'urlencoded', 'formdata'} else dict
                if not isinstance(value, expected):
                    errors.append(f'Postman body.{mode} has an invalid shape')
                if mode == 'raw' and isinstance(value, str):
                    options = body.get('options') or {}
                    raw_options = options.get('raw') or {} if isinstance(options, dict) else {}
                    language = raw_options.get('language') if isinstance(raw_options, dict) else None
                    if not isinstance(options, dict) or not isinstance(raw_options, dict):
                        errors.append('Postman body.options.raw must be an object')
                    if language == 'json':
                        try:
                            strict_json(VARIABLE.sub('0', value))
                            try:
                                scan(strict_json(value), names)
                            except ValueError:
                                # Bare numeric placeholders can prevent parsing; check quoted secrets directly.
                                for key, literal in re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', value):
                                    if CREDENTIAL.search(key) and literal and not VARIABLE.search(literal):
                                        errors.append('Postman credential raw JSON field must use a variable: ' + key)
                        except (ValueError, TypeError):
                            errors.append('Postman raw JSON body is invalid after variable substitution')
        if not tests:
            errors.append('Postman every request needs an inherited or local pm.test assertion script')

    if 'item' not in doc:
        errors.append('Postman item array is required')
    else:
        visit(doc, set())
    if 'baseUrl' not in defaults:
        errors.append('Postman collection variable baseUrl is required')
    else:
        base = defaults['baseUrl']
        if base:
            try:
                parsed = urlsplit(base) if isinstance(base, str) else None
                safe = parsed and parsed.scheme in {'http', 'https'} and parsed.hostname in {'localhost', '127.0.0.1', '::1'} and not parsed.username and not parsed.password
            except ValueError:
                safe = False
            if not safe:
                errors.append('Postman baseUrl default must be empty or a loopback URL')
    missing = sorted(route_key(e) for e in endpoints if route_key(e) not in seen_routes)
    if missing:
        errors.append('Postman declared endpoint coverage is missing: ' + ', '.join(missing))
    if request_count and not endpoints:
        errors.append('Postman nonempty collections require api_endpoints declarations')
    if not request_count and not text_description((info or {}).get('description') if isinstance(info, dict) else None).strip():
        errors.append('Postman empty collection requires an explanatory info.description')
    return list(dict.fromkeys(errors))
