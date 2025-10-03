# contacts_manager.py
import pandas as pd
import re
import requests
import json
from typing import List, Dict, Any

class ContactsManager:
    def __init__(self):
        self.groups = {}
        self.validated_contacts = {}
    
    def import_contacts(self, file_path: str, group_name: str) -> Dict[str, Any]:
        """Import contacts from CSV or Excel file with validation and enrichment"""
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            
            contacts = []
            valid_count = 0
            invalid_count = 0
            enriched_count = 0
            invalid_emails = []
            
            for _, row in df.iterrows():
                email = str(row.get('email', '')).strip().lower()
                
                if not self._is_valid_email(email):
                    invalid_emails.append(email)
                    invalid_count += 1
                    continue
                
                # Basic contact info
                contact = {
                    'email': email,
                    'first_name': str(row.get('first_name', '')).strip(),
                    'last_name': str(row.get('last_name', '')).strip(),
                    'phone': str(row.get('phone', '')).strip(),
                    'company': str(row.get('company', '')).strip(),
                    'country': str(row.get('country', '')).strip()
                }
                
                # Enrich contact data if missing first/last name
                if not contact['first_name'] or not contact['last_name']:
                    enriched_contact = self._enrich_contact_data(contact)
                    if enriched_contact:
                        contact = enriched_contact
                        enriched_count += 1
                
                contacts.append(contact)
                valid_count += 1
            
            # Organize into batches of 100
            batches = self._create_batches(contacts)
            self.groups[group_name] = batches
            self.validated_contacts[group_name] = contacts
            
            return {
                'total': len(df),
                'valid': valid_count,
                'invalid': invalid_count,
                'enriched': enriched_count,
                'invalid_emails': invalid_emails,
                'batches': len(batches)
            }
            
        except Exception as e:
            raise Exception(f"Error reading file: {str(e)}")
    
    def _is_valid_email(self, email: str) -> bool:
        """Comprehensive email validation"""
        if not email or pd.isna(email):
            return False
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False
        
        # Additional checks
        if email.count('@') != 1:
            return False
        
        local_part, domain = email.split('@')
        if len(local_part) == 0 or len(domain) == 0:
            return False
        
        return True
    
    def _enrich_contact_data(self, contact: Dict) -> Dict:
        """Enrich contact data using free APIs (placeholder implementation)"""
        try:
            # This is a placeholder - you can integrate with services like:
            # - Hunter.io (domain search)
            # - Clearbit (enrichment)
            # - Email verification services
            
            # For now, we'll use a simple mock enrichment
            email = contact['email']
            domain = email.split('@')[1]
            
            # Mock enrichment based on domain
            if not contact['first_name']:
                contact['first_name'] = 'Subscriber'
            if not contact['last_name']:
                contact['last_name'] = f"from {domain}"
            
            return contact
            
        except Exception:
            return contact
    
    def _create_batches(self, contacts: List[Dict], batch_size: int = 100) -> List[Dict]:
        """Create batches for sending"""
        batches = []
        for i in range(0, len(contacts), batch_size):
            batch_contacts = contacts[i:i + batch_size]
            batches.append({
                'number': len(batches) + 1,
                'contacts': batch_contacts,
                'count': len(batch_contacts)
            })
        return batches
    
    def list_groups(self) -> List[str]:
        return list(self.groups.keys())
    
    def get_group_stats(self, group_name: str) -> Dict[str, Any]:
        if group_name not in self.groups:
            return {'total': 0, 'valid': 0, 'invalid': 0, 'batches': 0}
        
        total_contacts = len(self.validated_contacts.get(group_name, []))
        batches = self.groups[group_name]
        
        return {
            'total': total_contacts,
            'valid': total_contacts,  # All are validated
            'invalid': 0,
            'batches': len(batches)
        }
    
    def get_batches(self, group_name: str) -> List[Dict]:
        return self.groups.get(group_name, [])
    
    def get_contacts(self, group_name: str, batch_number: int = None) -> List[Dict]:
        """Get contacts for a specific batch or all contacts"""
        if batch_number:
            batches = self.groups.get(group_name, [])
            for batch in batches:
                if batch['number'] == batch_number:
                    return batch['contacts']
            return []
        else:
            return self.validated_contacts.get(group_name, [])