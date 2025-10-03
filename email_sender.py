# email_sender.py
import smtplib
import os
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict
import uuid

class EmailSender:
    def __init__(self):
        self.providers = self._load_providers()
        self.stats = {
            'total_sent': 0,
            'successful': 0,
            'failed': 0,
            'unsubscribes': 0
        }
        self.unsubscribe_links = {}
    
    def _load_providers(self) -> Dict:
        """Load email providers from environment variables"""
        providers = {}
        
        # Mailjet
        if os.getenv('MAILJET_API_KEY') and os.getenv('MAILJET_SECRET'):
            providers['mailjet'] = {
                'type': 'api',
                'api_key': os.getenv('MAILJET_API_KEY'),
                'api_secret': os.getenv('MAILJET_SECRET')
            }
        
        # SMTP
        if all(os.getenv(var) for var in ['SMTP_WEBMAIL_HOST', 'SMTP_WEBMAIL_USER', 'SMTP_WEBMAIL_PASS']):
            providers['smtp'] = {
                'type': 'smtp',
                'host': os.getenv('SMTP_WEBMAIL_HOST'),
                'port': int(os.getenv('SMTP_WEBMAIL_PORT', '587')),
                'user': os.getenv('SMTP_WEBMAIL_USER'),
                'password': os.getenv('SMTP_WEBMAIL_PASS')
            }
        
        return providers
    
    def send_campaign(self, campaign_data: Dict, contacts_manager) -> Dict[str, int]:
        """Send email campaign with personalization and unsubscribe links"""
        group_name = campaign_data['group']
        batch_data = campaign_data.get('batch', 'all')
        
        if batch_data == 'all':
            contacts = contacts_manager.get_contacts(group_name)
        else:
            contacts = contacts_manager.get_contacts(group_name, int(batch_data))
        
        successful = 0
        failed = 0
        
        for contact in contacts:
            try:
                # Generate unsubscribe link
                unsubscribe_id = str(uuid.uuid4())
                unsubscribe_link = f"https://yourapp.com/unsubscribe/{unsubscribe_id}"
                self.unsubscribe_links[unsubscribe_id] = contact['email']
                
                # Personalize content
                if campaign_data.get('template_type') == 'html':
                    template = campaign_data.get('template')
                    # In real implementation, load template content
                    personalized_content = self._personalize_html(
                        "<html><body>Template content</body></html>", 
                        contact, 
                        unsubscribe_link
                    )
                    subject = campaign_data.get('subject', 'No Subject')
                else:
                    # Text email
                    body = campaign_data.get('body', '')
                    personalized_content = self._personalize_text(body, contact, unsubscribe_link)
                    subject = campaign_data.get('subject', 'No Subject')
                
                # Send email
                if self.providers.get('smtp'):
                    self._send_smtp(
                        to_email=contact['email'],
                        subject=subject,
                        content=personalized_content,
                        is_html=(campaign_data.get('template_type') == 'html')
                    )
                
                successful += 1
                self.stats['total_sent'] += 1
                self.stats['successful'] += 1
                
                # Rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Failed to send to {contact['email']}: {str(e)}")
                failed += 1
                self.stats['failed'] += 1
        
        self.stats['unsubscribes'] = len(self.unsubscribe_links)
        
        return {
            'total': len(contacts),
            'successful': successful,
            'failed': failed,
            'unsubscribes': len(self.unsubscribe_links)
        }
    
    def _personalize_html(self, html: str, contact: Dict, unsubscribe_link: str) -> str:
        """Personalize HTML template"""
        personalized = html
        for key, value in contact.items():
            personalized = personalized.replace(f'{{{{{key}}}}}', str(value))
        personalized = personalized.replace('{{unsubscribe_link}}', unsubscribe_link)
        return personalized
    
    def _personalize_text(self, text: str, contact: Dict, unsubscribe_link: str) -> str:
        """Personalize text template"""
        personalized = text
        for key, value in contact.items():
            personalized = personalized.replace(f'{{{{{key}}}}}', str(value))
        personalized = personalized.replace('{{unsubscribe_link}}', unsubscribe_link)
        return personalized
    
    def _send_smtp(self, to_email: str, subject: str, content: str, is_html: bool = True):
        """Send email via SMTP"""
        smtp_config = self.providers['smtp']
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = os.getenv('DEFAULT_SENDER_EMAIL', 'noreply@example.com')
        msg['To'] = to_email
        
        if is_html:
            msg.attach(MIMEText(content, 'html'))
        else:
            msg.attach(MIMEText(content, 'plain'))
        
        with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
            server.starttls()
            server.login(smtp_config['user'], smtp_config['password'])
            server.send_message(msg)
    
    def get_stats(self) -> Dict[str, int]:
        return self.stats.copy()