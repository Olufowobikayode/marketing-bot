# template_manager.py
import os
from typing import Dict, List

class TemplateManager:
    def __init__(self):
        self.templates = {}
        self.template_dir = "templates"
        os.makedirs(self.template_dir, exist_ok=True)
    
    def save_template(self, name: str, content: str, template_type: str = "html"):
        """Save template with type"""
        self.templates[name] = {
            'content': content,
            'type': template_type
        }
        
        # Also save to file
        file_path = os.path.join(self.template_dir, f"{name}.{template_type}")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def list_templates(self) -> List[str]:
        return list(self.templates.keys())
    
    def get_template(self, name: str) -> Dict:
        return self.templates.get(name, {})