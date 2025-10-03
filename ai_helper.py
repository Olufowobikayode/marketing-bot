# ai_helper.py
import os
import requests
from typing import Dict

class AIHelper:
    def __init__(self):
        self.api_key = os.getenv('GEMINI_API_KEY')
    
    def generate_copy(self, prompt: str) -> Dict[str, str]:
        """Generate marketing copy using AI"""
        try:
            # This is a simplified version - you'd integrate with Gemini API
            # For now, using mock responses
            mock_responses = {
                'product launch': {
                    'subject': '🎉 Exciting New Product Launch!',
                    'body': 'Dear {{first_name}},\n\nWe are thrilled to announce our new product! Get exclusive early access and special discounts.\n\nBest regards,\nThe Team'
                },
                'welcome email': {
                    'subject': '👋 Welcome to Our Community!',
                    'body': 'Hello {{first_name}},\n\nThank you for joining us! We are excited to have you in our community.\n\nBest regards,\nThe Team'
                },
                'discount': {
                    'subject': '🤑 Special Discount Just For You!',
                    'body': 'Hi {{first_name}},\n\nAs a valued member, we are offering you an exclusive discount. Use code: SAVE20\n\nBest regards,\nThe Team'
                }
            }
            
            # Find the best matching prompt
            for key in mock_responses:
                if key in prompt.lower():
                    return mock_responses[key]
            
            # Default response
            return {
                'subject': f'Update: {prompt[:30]}...',
                'body': f'Hello {{first_name}},\n\n{prompt}\n\nBest regards,\nThe Team'
            }
            
        except Exception as e:
            return {
                'subject': 'Important Update',
                'body': 'Hello {{first_name}},\n\nWe have an important update for you.\n\nBest regards,\nThe Team'
            }
    
    def score_email(self, subject: str, body: str) -> int:
        """Score email quality (1-10)"""
        score = 5  # Base score
        
        # Subject scoring
        if len(subject) > 0 and len(subject) <= 60:
            score += 2
        if any(char in subject for char in ['🎉', '👋', '🤑', '🔥']):
            score += 1
        
        # Body scoring
        if '{{first_name}}' in body:
            score += 1
        if len(body) >= 50 and len(body) <= 500:
            score += 1
        
        return min(10, score)