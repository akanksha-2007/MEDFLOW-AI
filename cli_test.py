#!/usr/bin/env python
"""
Interactive CLI for testing the healthcare navigation agent.
Run with: python cli_test.py

Allows you to:
- Chat with the agent as a patient
- View conversation history
- Test different scenarios
"""

import requests
import json
import sys
from typing import Optional, List, Dict, Any
from datetime import datetime


class AgentCLI:
    """Interactive CLI for testing the agent."""
    
    BASE_URL = "http://localhost:8000"
    
    def __init__(self):
        self.patient_id: Optional[str] = None
        self.conversation_history: List[Dict[str, str]] = []
        self.running = True
    
    def print_header(self):
        """Print welcome header."""
        print("\n" + "=" * 70)
        print("  HEALTHCARE NAVIGATION AI AGENT - INTERACTIVE TEST CLI")
        print("=" * 70)
        print("\nCommands:")
        print("  chat <message>     - Send a message to the agent")
        print("  history            - Show conversation history")
        print("  clear              - Clear conversation history")
        print("  patient <id>       - Set patient ID (or leave empty to select)")
        print("  patients           - List test patients")
        print("  tools              - Show available tools")
        print("  help               - Show this help")
        print("  exit               - Exit the program")
        print("-" * 70 + "\n")
    
    def list_test_patients(self):
        """List available test patients."""
        print("\nTest Patients (from seed_data.py):")
        print("  P001 - John Smith (65, Male)")
        print("    - Medical history: Hypertension, Type 2 Diabetes, chest pain")
        print("    - Medications: Lisinopril (DUPLICATE!), Metformin, Aspirin")
        print("    - Tests: Stress test, Blood sugar, Cholesterol panel")
        print("\n  P002 - Maria Garcia (52, Female)")
        print("    - (Additional patient in database)")
        print()
    
    def set_patient(self):
        """Set the active patient."""
        self.list_test_patients()
        patient_id = input("Enter Patient ID (e.g., P001): ").strip()
        
        if not patient_id:
            print("No patient ID provided.")
            return False
        
        self.patient_id = patient_id
        self.conversation_history = []
        print(f"\n✓ Patient set to: {patient_id}")
        print("Conversation history cleared.")
        return True
    
    def send_message(self, message: str):
        """Send a message to the agent."""
        if not self.patient_id:
            print("❌ Please set a patient ID first with: patient <id>")
            return
        
        try:
            print(f"\n📤 Sending message...")
            response = requests.post(
                f"{self.BASE_URL}/agent/chat",
                json={
                    "patient_id": self.patient_id,
                    "message": message,
                    "conversation_history": self.conversation_history
                },
                timeout=30
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"   {error_data.get('error', 'Unknown error')}")
                except:
                    print(f"   {response.text}")
                return
            
            data = response.json()
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": message})
            self.conversation_history.append({"role": "assistant", "content": data["reply"]})
            
            # Print agent response
            print(f"\n🤖 Agent Response:")
            print("-" * 70)
            print(data["reply"])
            print("-" * 70)
            
            # Show tool calls if any
            if data["tool_calls_made"]:
                print(f"\n🔧 Tools Used ({len(data['tool_calls_made'])}):")
                for tool_call in data["tool_calls_made"]:
                    print(f"  ✓ {tool_call['tool']}")
                    if tool_call['arguments']:
                        print(f"    Arguments: {json.dumps(tool_call['arguments'], indent=6)}")
            
            # Show structured data summary
            if data["structured_data"]:
                print(f"\n📊 Data Retrieved:")
                for tool_name, result in data["structured_data"].items():
                    if isinstance(result, dict):
                        # Show summary instead of full data
                        if "error" in result:
                            print(f"  ❌ {tool_name}: Error - {result['error']}")
                        elif "conflict_count" in result:
                            print(f"  🔍 {tool_name}: {result.get('conflict_count')} conflicts found")
                        elif "total_events" in result:
                            print(f"  📋 {tool_name}: {result.get('total_events')} events retrieved")
                        elif "total_pending" in result:
                            print(f"  ⏰ {tool_name}: {result.get('total_pending')} pending follow-ups")
                        elif "recommendation_count" in result:
                            print(f"  👨‍⚕️ {tool_name}: {result.get('recommendation_count')} recommendations")
                        else:
                            print(f"  ✓ {tool_name}: Data received")
            
            print(f"\n📅 Timestamp: {data['timestamp']}")
        
        except requests.exceptions.ConnectionError:
            print("❌ Cannot connect to server. Make sure it's running on http://localhost:8000")
            print("   Run: python main.py")
        except requests.exceptions.Timeout:
            print("❌ Request timed out. The agent might be waiting for LLM API.")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    def show_history(self):
        """Show conversation history."""
        if not self.patient_id:
            print("❌ Please set a patient ID first with: patient <id>")
            return
        
        if not self.conversation_history:
            print("\n(No conversation history yet)")
            return
        
        print(f"\n📜 Conversation History for {self.patient_id}:")
        print("-" * 70)
        
        for i, msg in enumerate(self.conversation_history, 1):
            role = "👤 You" if msg["role"] == "user" else "🤖 Agent"
            print(f"\n[{i}] {role}:")
            
            # Wrap long text
            content = msg["content"]
            if len(content) > 70:
                words = content.split()
                line = ""
                for word in words:
                    if len(line) + len(word) + 1 > 70:
                        print(f"    {line}")
                        line = word
                    else:
                        line += (" " if line else "") + word
                if line:
                    print(f"    {line}")
            else:
                print(f"    {content}")
        
        print("\n" + "-" * 70)
    
    def clear_history(self):
        """Clear conversation history."""
        if not self.patient_id:
            print("❌ Please set a patient ID first")
            return
        
        try:
            print(f"Clearing history for {self.patient_id}...")
            response = requests.delete(
                f"{self.BASE_URL}/agent/conversation/{self.patient_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                self.conversation_history = []
                print("✓ Conversation history cleared")
            else:
                print(f"❌ Error: {response.status_code}")
        
        except requests.exceptions.ConnectionError:
            print("❌ Cannot connect to server")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    def show_tools(self):
        """Show available tools."""
        try:
            print("📡 Fetching available tools...")
            response = requests.get(
                f"{self.BASE_URL}/agent/tools",
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.status_code}")
                return
            
            data = response.json()
            print(f"\n🔧 Available Tools ({data['total_tools']}):")
            print("-" * 70)
            
            for tool in data["tools"]:
                print(f"\n📌 {tool['name']}")
                print(f"   {tool['description']}")
                
                params = tool.get("parameters", {}).get("properties", {})
                if params:
                    print(f"   Parameters:")
                    for param_name, param_info in params.items():
                        param_type = param_info.get("type", "unknown")
                        param_desc = param_info.get("description", "")
                        print(f"     - {param_name} ({param_type}): {param_desc}")
            
            print("\n" + "-" * 70)
        
        except requests.exceptions.ConnectionError:
            print("❌ Cannot connect to server")
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    def run(self):
        """Main CLI loop."""
        self.print_header()
        
        # Initialize with a test patient
        print("First, let's select a patient to test with.\n")
        if not self.set_patient():
            return
        
        print("\nYou can now chat with the agent. Type 'help' for commands.\n")
        
        while self.running:
            try:
                user_input = input(">>> ").strip()
                
                if not user_input:
                    continue
                
                # Parse command
                parts = user_input.split(maxsplit=1)
                command = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                
                if command == "exit" or command == "quit":
                    print("Goodbye! 👋")
                    self.running = False
                
                elif command == "chat":
                    if not arg:
                        print("Usage: chat <message>")
                    else:
                        self.send_message(arg)
                
                elif command == "history":
                    self.show_history()
                
                elif command == "clear":
                    self.clear_history()
                
                elif command == "patient":
                    self.set_patient()
                
                elif command == "patients":
                    self.list_test_patients()
                
                elif command == "tools":
                    self.show_tools()
                
                elif command == "help":
                    print()
                    self.print_header()
                
                else:
                    # Treat as a chat message
                    self.send_message(user_input)
            
            except KeyboardInterrupt:
                print("\n\nGoodbye! 👋")
                self.running = False
            except Exception as e:
                print(f"Error: {str(e)}")


if __name__ == "__main__":
    cli = AgentCLI()
    cli.run()
