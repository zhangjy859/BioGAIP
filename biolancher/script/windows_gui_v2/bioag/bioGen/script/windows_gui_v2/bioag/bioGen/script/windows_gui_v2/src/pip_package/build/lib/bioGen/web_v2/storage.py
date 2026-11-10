import os
import json
import asyncio
import datetime
import uuid as uuid4
import sqlite3
import time
import tempfile

class BaseStorage:
    """
    Storage interface. Base class implements unchanged shared logic.
    """
    def __init__(self, persist_dir):
        self.persist_dir = persist_dir
        os.makedirs(self.persist_dir, exist_ok=True)

    def save_agents(self, team, file_path):
        # 强制要求：Agents team 状态的持久化保持不变 (必须保持 JSON 格式)
        agent_state = asyncio.run(team.save_state())
        def _convert_datetimes(data):
            if isinstance(data, dict):
                return {k: _convert_datetimes(v) for k, v in data.items()}
            elif isinstance(data, list):
                return [_convert_datetimes(item) for item in data]
            elif isinstance(data, datetime.datetime):
                return data.isoformat()
            return data
        
        agent_state = _convert_datetimes(agent_state)
        
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path) or self.persist_dir)
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(agent_state, f)
        os.replace(temp_path, file_path)
        return file_path

    def json_safedump(self, obj, fp, uuid=None, **kwargs):
        if not isinstance(obj, dict):
            raise ValueError("obj must be a dict")
        if uuid is None:
            uuid = str(uuid4.uuid4())
        obj_with_meta = {**obj, "message_uuid": uuid, "message_processed": False}
        json_str = json.dumps(obj_with_meta, **kwargs)
        fp.write(json_str + '\n')
        fp.flush()
        os.fsync(fp.fileno())

    def load_session(self, username, state): pass
    def save_session(self, username, state): pass
    def delete_session(self, username, state): pass
    def safe_append(self, file_path, data_dict, username=None): pass
    def get_user_prompt_history(self, username, file_path=None): pass
    def backup_session(self, username, state): pass
    def export_session_to_json(self, username, state): pass


class JsonStorage(BaseStorage):
    def _get_session_key(self, username):
        return username

    def _get_session_file(self, username):
        return os.path.join(self.persist_dir, f"{self._get_session_key(username)}.json")

    def load_session(self, username, state):
        session_file = self._get_session_file(username)
        if os.path.exists(session_file):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)
                    state.messages = data.get('messages', [])
                    state.prompt_history = data.get('prompt_history', "")
                    if 'project_id' in data:
                        state.project_id = data['project_id']
                    state.processing = data.get('processing', False)
                    for key in ['pending_prompt', 'pending_prompt_type', 'input_prompt']:
                        if key in data:
                            state[key] = data[key]
            except Exception:
                pass
        if not state.get('reload_session', False):
            state.reload_session = True

    def save_session(self, username, state):
        if state.get('messages', "") == "":
            return
        session_file = self._get_session_file(username)
        data = {
            'messages': state.get('messages', []),
            'prompt_history': state.get('prompt_history', ""),
            'project_id': state.get('project_id', None),
            'processing': state.get('processing', False),
            'pending_prompt': state.get('pending_prompt', None),
            'pending_prompt_type': state.get('pending_prompt_type', None),
            'input_prompt': state.get('input_prompt', False)
        }
        temp_fd, temp_path = tempfile.mkstemp(dir=self.persist_dir)
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(data, f)
        os.replace(temp_path, session_file)

    def delete_session(self, username, state=None):
        session_file = self._get_session_file(username)
        if os.path.exists(session_file):
            os.remove(session_file)

    def safe_append(self, file_path, data_dict, username=None):
        data = []
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
            except Exception: pass
        data.append(data_dict)
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path) or self.persist_dir)
        with os.fdopen(temp_fd, 'w') as f:
            json.dump(data, f)
        os.replace(temp_path, file_path)

    def get_user_prompt_history(self, username, file_path=None):
        if not file_path:
            file_path = os.path.join(self.persist_dir, f"{username}_input.ujson")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    return data[0]['message'] if data and isinstance(data, list) else None
            except Exception: pass
        return None

    def backup_session(self, username, state=None):
        session_file = self._get_session_file(username)
        if os.path.exists(session_file):
            os.rename(session_file, os.path.join(self.persist_dir, f"{self._get_session_key(username)}_{int(time.time())}.json"))

    def export_session_to_json(self, username, state=None):
        return self._get_session_file(username)


class SqliteStorage(BaseStorage):
    def __init__(self, persist_dir):
        super().__init__(persist_dir)
        self.db_path = os.path.join(self.persist_dir, 'bio_sessions.db')
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS kv_sessions (
                    session_key TEXT PRIMARY KEY,
                    data_json TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_inputs (
                    file_path TEXT PRIMARY KEY,
                    data_json TEXT
                )
            ''')
            conn.commit()

    def _get_session_key(self, username):
        return username

    def load_session(self, username, state):
        session_key = self._get_session_key(username)
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT data_json FROM kv_sessions WHERE session_key = ?', (session_key,))
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row[0])
                    state.messages = data.get('messages', [])
                    state.prompt_history = data.get('prompt_history', "")
                    if 'project_id' in data:
                        state.project_id = data['project_id']
                    state.processing = data.get('processing', False)
                    for key in ['pending_prompt', 'pending_prompt_type', 'input_prompt']:
                        if key in data:
                            state[key] = data[key]
                except Exception:
                    pass
        if not state.get('reload_session', False):
            state.reload_session = True

    def save_session(self, username, state):
        if state.get('messages', "") == "":
            return
        session_key = self._get_session_key(username)
        data = {
            'messages': state.get('messages', []),
            'prompt_history': state.get('prompt_history', ""),
            'project_id': state.get('project_id', None),
            'processing': state.get('processing', False),
            'pending_prompt': state.get('pending_prompt', None),
            'pending_prompt_type': state.get('pending_prompt_type', None),
            'input_prompt': state.get('input_prompt', False)
        }
        with self._get_conn() as conn:
            conn.execute('INSERT OR REPLACE INTO kv_sessions (session_key, data_json) VALUES (?, ?)', (session_key, json.dumps(data)))
            conn.commit()

    def delete_session(self, username, state=None):
        session_key = self._get_session_key(username)
        with self._get_conn() as conn:
            conn.execute('DELETE FROM kv_sessions WHERE session_key = ?', (session_key,))
            conn.commit()

    def safe_append(self, file_path, data_dict, username=None):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT data_json FROM user_inputs WHERE file_path = ?', (file_path,))
            row = cursor.fetchone()
            data = json.loads(row[0]) if row else []
            data.append(data_dict)
            conn.execute('INSERT OR REPLACE INTO user_inputs (file_path, data_json) VALUES (?, ?)', (file_path, json.dumps(data)))
            conn.commit()

    def get_user_prompt_history(self, username, file_path=None):
        if not file_path:
            file_path = os.path.join(self.persist_dir, f"{username}_input.ujson")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT data_json FROM user_inputs WHERE file_path = ?', (file_path,))
            row = cursor.fetchone()
            if row:
                try:
                    data = json.loads(row[0])
                    if data and isinstance(data, list):
                        return data[0].get('message')
                except Exception: pass
        return None

    def backup_session(self, username, state=None):
        session_key = self._get_session_key(username)
        backup_key = f"{session_key}_{int(time.time())}"
        with self._get_conn() as conn:
            conn.execute('UPDATE kv_sessions SET session_key = ? WHERE session_key = ?', (backup_key, session_key))
            conn.commit()

    def export_session_to_json(self, username, state=None):
        session_key = self._get_session_key(username)
        temp_file = os.path.join(self.persist_dir, f"{session_key}_temp_summary.json")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT data_json FROM kv_sessions WHERE session_key = ?', (session_key,))
            row = cursor.fetchone()
            with open(temp_file, 'w') as f:
                f.write(row[0] if row else '{}')
        return temp_file

def get_storage(persist_dir):
    """
    user export USE_SQLITE=true to enable SQLite
    """
    use_sqlite = os.environ.get("USE_SQLITE", "false").lower() in ["true", "1", "yes"]
    if use_sqlite:
        return SqliteStorage(persist_dir)
    return JsonStorage(persist_dir)
