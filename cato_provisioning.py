#!/usr/bin/env python3

import requests
import json
import csv
import time
import uuid
import os
import configparser
from typing import Dict, List, Optional, Any
from pathlib import Path
import logging
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich import box

console = Console()


class ConfigManager:
    def __init__(self, config_file: str = "config.ini"):
        self.config = configparser.ConfigParser()
        if not Path(config_file).exists():
            raise FileNotFoundError(f"Fichier de configuration non trouve: {config_file}")
        self.config.read(config_file)
    
    def get(self, section: str, key: str, fallback: Any = None) -> str:
        env_key = f"CATO_{section.upper()}_{key.upper()}"
        env_value = os.environ.get(env_key)
        if env_value:
            return env_value
        return self.config.get(section, key, fallback=fallback)
    
    def getboolean(self, section: str, key: str, fallback: bool = False) -> bool:
        env_key = f"CATO_{section.upper()}_{key.upper()}"
        env_value = os.environ.get(env_key)
        if env_value:
            return env_value.lower() in ('true', '1', 'yes', 'on')
        return self.config.getboolean(section, key, fallback=fallback)
    
    def getfloat(self, section: str, key: str, fallback: float = 0.0) -> float:
        env_key = f"CATO_{section.upper()}_{key.upper()}"
        env_value = os.environ.get(env_key)
        if env_value:
            return float(env_value)
        return self.config.getfloat(section, key, fallback=fallback)


class HTTPLogger:
    def __init__(self, log_file: Path, enabled: bool = True):
        self.enabled = enabled
        self.log_file = log_file
        self.logs = []
    
    def log_request_response(self, request_id: str, request_data: Dict, response_data: Dict, 
                            duration: float, error: Optional[str] = None):
        if not self.enabled:
            return
        self.logs.append({
            "request_id": request_id,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(duration, 3),
            "request": request_data,
            "response": response_data,
            "error": error
        })
    
    def save(self):
        if not self.enabled or not self.logs:
            return
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "total_requests": len(self.logs),
                "logs": self.logs
            }, f, indent=2, ensure_ascii=False)
    
    def get_stats(self) -> Dict:
        if not self.logs:
            return {}
        durations = [log['duration_seconds'] for log in self.logs]
        errors = [log for log in self.logs if log.get('error')]
        return {
            "total_requests": len(self.logs),
            "successful_requests": len(self.logs) - len(errors),
            "failed_requests": len(errors),
            "total_duration": round(sum(durations), 2),
            "avg_duration": round(sum(durations) / len(durations), 3),
            "min_duration": round(min(durations), 3),
            "max_duration": round(max(durations), 3)
        }


class CatoGraphQLClient:
    def __init__(self, api_key: str, account_id: str, api_url: str, 
                 timeout: int = 30, http_logger: Optional[HTTPLogger] = None):
        self.api_url = api_url
        self.account_id = account_id
        self.timeout = timeout
        self.http_logger = http_logger
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-api-key": api_key
        })
    
    def execute(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        request_id = str(uuid.uuid4())[:8]
        console.print(f"[cyan]Request ID: {request_id}[/cyan]")
        
        payload = {"query": query, "variables": variables or {}}
        request_data = {
            "url": self.api_url,
            "method": "POST",
            "headers": {"x-api-key": "***" + self.session.headers.get("x-api-key", "")[-4:]},
            "payload": payload
        }
        
        start_time = time.time()
        error_msg = None
        response_data = {}
        
        try:
            response = self.session.post(self.api_url, json=payload, timeout=self.timeout)
            duration = time.time() - start_time
            
            try:
                response_body = response.json()
            except:
                response_body = {"raw_text": response.text}
            
            response_data = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response_body
            }
            
            response.raise_for_status()
            
            if "errors" in response_body:
                error_msg = f"GraphQL errors: {response_body['errors']}"
                if self.http_logger:
                    self.http_logger.log_request_response(request_id, request_data, response_data, duration, error_msg)
                raise Exception(error_msg)
            
            if self.http_logger:
                self.http_logger.log_request_response(request_id, request_data, response_data, duration)
            
            console.print(f"[green]Response: {response.status_code} ({duration:.2f}s)[/green]")
            return response_body
            
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            error_msg = str(e)
            
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_body = e.response.json()
                except:
                    error_body = {"raw_text": e.response.text if hasattr(e.response, 'text') else str(e)}
                response_data = {
                    "status_code": e.response.status_code,
                    "headers": dict(e.response.headers),
                    "body": error_body,
                    "error": error_msg
                }
            else:
                response_data = {"status_code": None, "headers": {}, "body": {}, "error": error_msg}
            
            if self.http_logger:
                self.http_logger.log_request_response(request_id, request_data, response_data, duration, error_msg)
            
            console.print(f"[red]Error: {error_msg}[/red]")
            raise


class CSVDataLoader:
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
    
    def load_data(self) -> List[Dict]:
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Fichier CSV non trouve: {self.csv_path}")
        data = []
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                filtered_row = {k: v for k, v in row.items() if v}
                data.append(filtered_row)
        return data


class JSONSequenceLoader:
    def __init__(self, json_path: str):
        self.json_path = Path(json_path)
    
    def load_sequence(self) -> Dict:
        if not self.json_path.exists():
            raise FileNotFoundError(f"Fichier JSON non trouve: {self.json_path}")
        
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        sequence = {
            'master_data_source': data.get('master_data_source', ''),
            'master_iterate_over': data.get('master_iterate_over', ''),
            'steps': []
        }
        
        for idx, step in enumerate(data.get('sequence', []), start=1):
            if not step.get('enabled', True):
                continue
            sequence['steps'].append({
                'step_name': step.get('step_name', f'step_{idx}'),
                'operation': step['operation'],
                'params': step.get('params', {}),
                'wait_seconds': float(step.get('wait_seconds', 1.0)),
                'store_result_as': step.get('store_result_as', ''),
                'iterate_over': step.get('iterate_over', ''),
                'iteration_scope': step.get('iteration_scope', 'global'),
                'graphql_query': step.get('graphql_query', ''),
                'data_source_file': step.get('data_source_file', ''),
                'join_on': step.get('join_on', {}),
                'filter_by': step.get('filter_by', {}),
                'condition': step.get('condition', {})
            })
        return sequence
    
    def resolve_variables(self, params: Dict, context: Dict, depth: int = 0) -> Dict:
        resolved = {}
        indent = "  " * depth
        
        for key, value in params.items():
            if isinstance(value, dict):
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"[dim]{indent}  Dict: {key}[/dim]")
                resolved[key] = self.resolve_variables(value, context, depth + 1)
            elif isinstance(value, list):
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"[dim]{indent}  List: {key}[/dim]")
                resolved[key] = [
                    self.resolve_variables(item, context, depth + 1) if isinstance(item, dict)
                    else self._resolve_single_value(item, context, f"{key}[{i}]", depth)
                    for i, item in enumerate(value)
                ]
            else:
                resolved_value = self._resolve_single_value(value, context, key, depth)
                if resolved_value is not None:
                    resolved[key] = resolved_value
        return resolved
    
    def _resolve_single_value(self, value: Any, context: Dict, key: str, depth: int = 0) -> Any:
        indent = "  " * depth
        
        if isinstance(value, str):
            if value.startswith('@'):
                column_name = value[1:]
                if 'iteration_row' in context and column_name in context['iteration_row']:
                    resolved_value = context['iteration_row'][column_name]
                    if resolved_value and str(resolved_value).strip():
                        if logging.getLogger().isEnabledFor(logging.DEBUG):
                            console.print(f"[dim]{indent}  {key}: @{column_name} = {resolved_value}[/dim]")
                        return resolved_value
                else:
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        console.print(f"[yellow]{indent}  {key}: @{column_name} NOT FOUND[/yellow]")
            
            elif value.startswith('${') and value.endswith('}'):
                var_name = value[2:-1]
                
                if '.' in var_name:
                    parts = var_name.split('.')
                    result = context.get(parts[0])
                    
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        console.print(f"[dim]{indent}  {key}: Resolving ${{{var_name}}}[/dim]")
                    
                    if result:
                        for part in parts[1:]:
                            if isinstance(result, dict):
                                result = result.get(part)
                            elif isinstance(result, list) and part.isdigit():
                                idx = int(part)
                                if 0 <= idx < len(result):
                                    result = result[idx]
                                else:
                                    result = None
                                    break
                            else:
                                result = None
                                break
                        
                        if result is not None:
                            if logging.getLogger().isEnabledFor(logging.DEBUG):
                                console.print(f"[green]{indent}  {key}: ${{{var_name}}} = {result}[/green]")
                            return result
                else:
                    if var_name in context and context[var_name] is not None:
                        if logging.getLogger().isEnabledFor(logging.DEBUG):
                            console.print(f"[green]{indent}  {key}: ${{{var_name}}} = {context[var_name]}[/green]")
                        return context[var_name]
            else:
                if value and str(value).strip():
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        console.print(f"[dim]{indent}  {key}: (static) = {value}[/dim]")
                    return value
        
        elif value is not None:
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                console.print(f"[dim]{indent}  {key}: (value) = {value}[/dim]")
            return value
        
        return None
    
    def evaluate_condition(self, condition: Dict, context: Dict) -> bool:
        if not condition:
            return True
        
        field = condition.get('field')
        operator = condition.get('operator', '==')
        value = condition.get('value')
        
        if not field:
            return True
        
        if field.startswith('@'):
            column_name = field[1:]
            if 'iteration_row' in context and column_name in context['iteration_row']:
                field_value = context['iteration_row'][column_name]
            else:
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"[yellow]    Condition field '@{column_name}' not found[/yellow]")
                    console.print(f"[yellow]    Available: {list(context.get('iteration_row', {}).keys())}[/yellow]")
                return False
        elif field.startswith('${') and field.endswith('}'):
            var_name = field[2:-1]
            field_value = context.get(var_name)
            if field_value is None:
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"[yellow]    Condition field '${{{var_name}}}' not found[/yellow]")
                return False
        else:
            field_value = field
        
        if isinstance(value, str) and value.startswith('@'):
            column_name = value[1:]
            if 'iteration_row' in context and column_name in context['iteration_row']:
                compare_value = context['iteration_row'][column_name]
            else:
                compare_value = value
        else:
            compare_value = value
        
        if operator == '==':
            result = field_value == compare_value
        elif operator == '!=':
            result = field_value != compare_value
        elif operator == 'in':
            result = field_value in compare_value if isinstance(compare_value, (list, tuple)) else False
        elif operator == 'not_in':
            result = field_value not in compare_value if isinstance(compare_value, (list, tuple)) else False
        elif operator == 'contains':
            result = compare_value in str(field_value)
        else:
            result = True
        
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            console.print(f"[cyan]    Condition: '{field_value}' {operator} '{compare_value}' = {result}[/cyan]")
        
        return result


class ProvisioningOrchestrator:
    def __init__(self, client: CatoGraphQLClient, config: ConfigManager):
        self.client = client
        self.config = config
        self.global_context = {}
    
    def execute_sequence(self, sequence: Dict, loader: JSONSequenceLoader, 
                        data_sources: Dict[str, List[Dict]] = None) -> List[Dict]:
        console.print(Panel(
            f"[bold cyan]Demarrage du provisionnement[/bold cyan]\n"
            f"[dim]{len(sequence['steps'])} etapes configurees[/dim]",
            border_style="cyan",
            width=80,
            padding=(0, 1)
        ))
        
        results = []
        data_sources = data_sources or {}
        
        if sequence.get('master_iterate_over'):
            master_source = sequence['master_iterate_over']
            master_file = sequence.get('master_data_source', '')
            
            if master_file and Path(master_file).exists():
                loader_csv = CSVDataLoader(master_file)
                data_sources[master_source] = loader_csv.load_data()
                console.print(f"[cyan]Dataset maitre charge: {len(data_sources[master_source])} entrees[/cyan]")
            
            if master_source not in data_sources:
                raise ValueError(f"Dataset maitre '{master_source}' non trouve")
            
            master_dataset = data_sources[master_source]
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                main_task = progress.add_task("[cyan]Batch...", total=len(master_dataset))
                
                for idx, master_row in enumerate(master_dataset, 1):
                    master_name = master_row.get('name', master_row.get('site_name', f'batch_{idx}'))
                    
                    console.print(f"\n[bold blue]{'=' * 80}[/bold blue]")
                    console.print(f"[bold cyan]BATCH {idx}/{len(master_dataset)}: {master_name}[/bold cyan]")
                    console.print(f"[bold blue]{'=' * 80}[/bold blue]")
                    
                    self.global_context = {'iteration_row': master_row, 'iteration_index': idx}
                    
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        console.print(f"[cyan]Starting batch with context: {list(self.global_context.keys())}[/cyan]")
                    
                    batch_results = self._execute_steps(sequence['steps'], loader, data_sources, progress)
                    results.extend(batch_results)
                    progress.update(main_task, advance=1)
        
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                main_task = progress.add_task("[cyan]Provisionnement...", total=len(sequence['steps']))
                results = self._execute_steps(sequence['steps'], loader, data_sources, progress)
                progress.update(main_task, completed=len(sequence['steps']))
        
        console.print(f"\n[bold green]{'=' * 80}[/bold green]")
        console.print("[bold green]Execution terminee[/bold green]")
        
        return results
    
    def _execute_steps(self, steps: List[Dict], loader: JSONSequenceLoader, 
                      data_sources: Dict, progress: Progress) -> List[Dict]:
        results = []
        
        for i, step in enumerate(steps, 1):
            console.print(f"\n[bold blue]{'-' * 80}[/bold blue]")
            console.print(f"[bold]Etape {i}/{len(steps)}: {step['step_name']}[/bold]")
            console.print(f"[dim]Operation: {step['operation']}[/dim]")
            
            if step.get('condition') and not step.get('iterate_over'):
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"[cyan]Evaluating step-level condition...[/cyan]")
                if not loader.evaluate_condition(step['condition'], self.global_context):
                    console.print(f"[yellow]Condition non satisfaite - Etape ignoree[/yellow]")
                    continue
            
            if step['iterate_over']:
                if step.get('data_source_file'):
                    source_name = step['iterate_over']
                    source_file = step['data_source_file']
                    if Path(source_file).exists():
                        temp_loader = CSVDataLoader(source_file)
                        data_sources[source_name] = temp_loader.load_data()
                        console.print(f"[cyan]Fichier charge: {len(data_sources[source_name])} entrees[/cyan]")
                
                step_results = self._execute_iteration(step, loader, data_sources, progress)
                results.extend(step_results)
            else:
                result = self._execute_single_step(step, loader, self.global_context)
                if result:
                    results.append(result)
                    if step['wait_seconds'] > 0:
                        time.sleep(step['wait_seconds'])
        
        return results
    
    def _execute_iteration(self, step: Dict, loader: JSONSequenceLoader, 
                          data_sources: Dict, progress: Progress) -> List[Dict]:
        iterate_over = step['iterate_over']
        
        if iterate_over not in data_sources:
            raise ValueError(f"Source de donnees '{iterate_over}' non trouvee")
        
        dataset = data_sources[iterate_over]
        
        if step.get('join_on'):
            dataset = self._apply_join(dataset, step['join_on'])
        
        if step.get('filter_by'):
            dataset = self._apply_filter(dataset, step['filter_by'])
        
        console.print(f"[yellow]Iteration sur {len(dataset)} elements[/yellow]")
        
        if len(dataset) == 0:
            console.print(f"[yellow]Aucun element a traiter[/yellow]")
            return []
        
        results = []
        iter_task = progress.add_task(f"[yellow]Iteration...", total=len(dataset))
        
        for idx, row in enumerate(dataset, 1):
            item_name = row.get('name', row.get('site_name', row.get('lan_name', f'item_{idx}')))
            progress.update(iter_task, description=f"[yellow]  {item_name}")
            
            context = dict(self.global_context)
            context['iteration_row'] = row
            context['iteration_index'] = idx
            
            if step.get('condition'):
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"  [cyan]Evaluating condition for {item_name}...[/cyan]")
                if not loader.evaluate_condition(step['condition'], context):
                    console.print(f"  [yellow]Condition non satisfaite pour {item_name}, ignore[/yellow]")
                    progress.update(iter_task, advance=1)
                    continue
                else:
                    if logging.getLogger().isEnabledFor(logging.DEBUG):
                        console.print(f"  [green]Condition satisfaite pour {item_name}[/green]")
            
            result = self._execute_single_step(step, loader, context, indent=True)
            
            if result and result['status'] == 'success':
                if step['store_result_as']:
                    self.global_context[step['store_result_as']] = result['result']
                results.append(result)
                if idx < len(dataset) and step['wait_seconds'] > 0:
                    time.sleep(step['wait_seconds'])
            elif result:
                results.append(result)
            
            progress.update(iter_task, advance=1)
        
        progress.remove_task(iter_task)
        return results
    
    def _apply_join(self, dataset: List[Dict], join_config: Dict) -> List[Dict]:
        local_key = join_config.get('local_key')
        context_key = join_config.get('context_key')
        
        if not local_key or not context_key:
            return dataset
        
        context_value = None
        if 'iteration_row' in self.global_context:
            context_value = self.global_context['iteration_row'].get(context_key)
        
        if not context_value:
            return dataset
        
        filtered = [row for row in dataset if row.get(local_key) == context_value]
        console.print(f"[dim]Jointure: {len(dataset)} -> {len(filtered)} elements[/dim]")
        return filtered
    
    def _apply_filter(self, dataset: List[Dict], filter_config: Dict) -> List[Dict]:
        filtered_data = dataset
        
        for field, value_expression in filter_config.items():
            if isinstance(value_expression, str) and value_expression.startswith('${'):
                var_name = value_expression[2:-1]
                filter_value = None
                if 'iteration_row' in self.global_context:
                    filter_value = self.global_context['iteration_row'].get(var_name)
                if not filter_value:
                    filter_value = self.global_context.get(var_name)
                if filter_value:
                    filtered_data = [row for row in filtered_data if row.get(field) == filter_value]
                    console.print(f"[dim]Filtre: {field} = {filter_value} -> {len(filtered_data)} elements[/dim]")
            else:
                filtered_data = [row for row in filtered_data if row.get(field) == value_expression]
                console.print(f"[dim]Filtre: {field} = {value_expression} -> {len(filtered_data)} elements[/dim]")
        return filtered_data
    
    def _execute_single_step(self, step: Dict, loader: JSONSequenceLoader, 
                            context: Dict, indent: bool = False) -> Optional[Dict]:
        prefix = "  " if indent else ""
        
        try:
            if logging.getLogger().isEnabledFor(logging.DEBUG):
                console.print(f"{prefix}[cyan]Context available: {list(context.keys())}[/cyan]")
                console.print(f"{prefix}[cyan]Resolving variables...[/cyan]")
            
            params = loader.resolve_variables(step['params'], context)
            params['accountId'] = self.client.account_id
            
            if not step.get('graphql_query'):
                raise ValueError(f"Pas de requete GraphQL pour '{step['step_name']}'")
            
            query = step['graphql_query']
            result = self.client.execute(query, params)
            
            if step['store_result_as']:
                self.global_context[step['store_result_as']] = result
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    console.print(f"{prefix}[green]Stored as '{step['store_result_as']}' in global context[/green]")
            
            console.print(f"{prefix}[green]Succes[/green]")
            
            return {
                'step_name': step['step_name'],
                'operation': step['operation'],
                'status': 'success',
                'result': result,
                'params': params,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            console.print(f"{prefix}[red]Erreur: {e}[/red]")
            return {
                'step_name': step['step_name'],
                'operation': step['operation'],
                'status': 'error',
                'error': str(e),
                'params': params if 'params' in locals() else {},
                'timestamp': datetime.now().isoformat()
            }
    
    def save_results(self, results: List[Dict], output_file: Path):
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        console.print(f"[green]Resultats sauvegardes: {output_file}[/green]")


def setup_logging(output_dir: Path, log_level: str):
    log_file = output_dir / f"execution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler(log_file, encoding='utf-8')],
        force=True
    )
    return log_file


def print_header():
    console.print("[bold green]Cato Networks - Provisioning Orchestrator v3.2[/bold green]")
    console.print("[dim]Mode batch avec conditions et variables d'environnement[/dim]\n")


def main():
    try:
        config = ConfigManager("config.ini")
        
        output_dir = Path(config.get('files', 'output_dir', fallback='./logs'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = setup_logging(output_dir, config.get('display', 'log_level', fallback='INFO'))
        
        print_header()
        
        http_log_file = output_dir / f"http_requests_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        http_logger = HTTPLogger(
            http_log_file,
            enabled=config.getboolean('execution', 'enable_http_logging', fallback=True)
        )
        
        client = CatoGraphQLClient(
            api_key=config.get('api', 'api_key'),
            account_id=config.get('api', 'account_id'),
            api_url=config.get('api', 'api_url', fallback='https://api.catonetworks.com/api/v1/graphql2'),
            timeout=config.getfloat('execution', 'request_timeout', fallback=30),
            http_logger=http_logger
        )
        
        sequence_file = config.get('files', 'sequence_file', fallback='provisioning_sequence.json')
        loader = JSONSequenceLoader(sequence_file)
        sequence = loader.load_sequence()
        
        console.print(f"[cyan]Sequence chargee: {len(sequence['steps'])} etapes[/cyan]")
        if sequence.get('master_iterate_over'):
            console.print(f"[cyan]Mode batch active: {sequence['master_iterate_over']}[/cyan]")
        console.print()
        
        orchestrator = ProvisioningOrchestrator(client, config)
        results = orchestrator.execute_sequence(sequence, loader, {})
        
        results_file = output_dir / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        orchestrator.save_results(results, results_file)
        
        http_logger.save()
        
        stats = http_logger.get_stats()
        if stats:
            table = Table(title="Statistiques HTTP", box=box.ROUNDED, width=80)
            table.add_column("Metrique", style="cyan")
            table.add_column("Valeur", style="green", justify="right")
            table.add_row("Total requetes", str(stats['total_requests']))
            table.add_row("Reussies", str(stats['successful_requests']))
            table.add_row("Echouees", str(stats['failed_requests']))
            table.add_row("Duree totale", f"{stats['total_duration']}s")
            table.add_row("Duree moyenne", f"{stats['avg_duration']}s")
            console.print(table)
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        error_count = len(results) - success_count
        
        summary_table = Table(title="Resume", box=box.DOUBLE_EDGE, width=80)
        summary_table.add_column("Statut", style="bold")
        summary_table.add_column("Nombre", justify="right")
        summary_table.add_row("[green]Reussies[/green]", f"[green]{success_count}[/green]")
        summary_table.add_row("[red]Echouees[/red]", f"[red]{error_count}[/red]")
        summary_table.add_row("[cyan]Total[/cyan]", f"[cyan]{len(results)}[/cyan]")
        console.print(summary_table)
        
        if error_count == 0:
            console.print("\n[bold green]Tous les elements ont ete provisionnes avec succes ![/bold green]\n")
        else:
            console.print(f"\n[bold yellow]{error_count} erreur(s) detectee(s). Consultez les logs.[/bold yellow]\n")
        
    except Exception as e:
        console.print(f"\n[bold red]Erreur fatale: {e}[/bold red]")
        raise


if __name__ == "__main__":
    main()