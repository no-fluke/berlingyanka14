import os
import logging
import requests
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Get port from environment variable (Render provides this)
port = int(os.environ.get('PORT', 5000))

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Course Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class CourseBot:
    def __init__(self, token: str):
        self.token = token
        self.application = Application.builder().token(token).build()
        self.api_base_url = "https://backend.multistreaming.site/api"
        self.user_preferences = {}
        self.available_courses = []
        self.setup_handlers()
        
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("batches", self.batches_command))
        self.application.add_handler(CommandHandler("get_course", self.get_course_command))
        self.application.add_handler(CommandHandler("quality", self.quality_command))
        self.application.add_handler(CallbackQueryHandler(self.quality_callback, pattern="^quality_"))
        self.application.add_handler(CallbackQueryHandler(self.course_callback, pattern="^course_"))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = "720p"
        
        welcome_text = f"""🤖 Course Data Bot

I can fetch course data from the API and send you formatted text files containing:

• Topics and classes
• Video lecture links (your chosen quality)
• PDF material links
• Teacher information

Your current video quality preference: {self.user_preferences[user_id]}

Commands:
/start - Show this message  
/help - Get help information  
/batches - Show all available batches
/quality - Change video quality preference  
/get_course - Fetch course data from API and get a text file"""
        await update.message.reply_text(welcome_text)
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """📖 Help Guide

/batches
- Shows all available courses/batches
- Select a batch to get its data

/get_course
- Fetches data from the course API
- Generates a .txt file with:
  • Course info
  • Topics and classes
  • Video links (your preferred quality)
  • PDF links with names

/quality
- Change your preferred video quality
- Available options: 240p, 360p, 480p, 720p, 1080p
- The bot will prioritize your chosen quality

The bot generates a structured text file with all the links."""
        await update.message.reply_text(help_text)
    
    async def batches_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show all available batches/courses"""
        await update.message.reply_text("📚 Fetching available batches...")
        
        try:
            # Fetch all courses from API
            api_url = f"{self.api_base_url}/courses"
            logger.info(f"Fetching batches from: {api_url}")
            
            response = requests.get(api_url, timeout=30)
            logger.info(f"API Response Status: {response.status_code}")
            
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"API Response Data: {data}")
            
            if data.get('state') != 200:
                error_msg = data.get('msg', 'Unknown error')
                logger.error(f"API returned error state: {error_msg}")
                await update.message.reply_text(f"❌ API Error: {error_msg}")
                return
            
            courses = data.get('data', [])
            logger.info(f"Found {len(courses)} courses")

            if not courses:
                await update.message.reply_text("❌ No batches found in the API.")
                return
            
            self.available_courses = courses
            context.user_data['available_courses'] = courses
            
            # Create keyboard with batches
            keyboard = []
            for i, course in enumerate(courses, 1):
                course_title = course.get('title', f'Batch {i}')[:64]  # Limit title length
                keyboard.append([InlineKeyboardButton(f"{i}. {course_title}", callback_data=f"course_{i-1}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📚 Available Batches ({len(courses)} found):\n\nClick on a batch to get its data:",
                reply_markup=reply_markup
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching batches: {e}")
            await update.message.reply_text("❌ Network error fetching batches. Please try again later.")
        except Exception as e:
            logger.error(f"Unexpected error fetching batches: {e}")
            await update.message.reply_text("❌ Error fetching batches. Please try again later.")
    
    async def course_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle course selection"""
        query = update.callback_query
        await query.answer()
        
        try:
            course_index = int(query.data.replace("course_", ""))
            courses = context.user_data.get('available_courses', [])
            
            if not courses or course_index >= len(courses):
                await query.edit_message_text("❌ Course not found. Please try /batches again.")
                return
            
            selected_course = courses[course_index]
            course_id = selected_course.get('id')
            course_title = selected_course.get('title', 'Unknown Course')
            
            # Store selected course ID in context for get_course_command
            context.user_data['selected_course_id'] = course_id
            context.user_data['selected_course_title'] = course_title
            
            # Automatically fetch course data and send as file
            await query.edit_message_text(f"✅ Selected: {course_title}\n\nFetching course data...")
            await self.fetch_and_send_course_data(update, context, course_id, course_title)
            
        except Exception as e:
            logger.error(f"Error in course callback: {e}")
            await query.edit_message_text("❌ Error selecting course. Please try again.")
    
    async def get_course_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetch course data for the selected batch"""
        user_id = update.effective_user.id
        preferred_quality = self.user_preferences.get(user_id, "720p")
        
        # Check if we have a selected course
        course_id = context.user_data.get('selected_course_id')
        course_title = context.user_data.get('selected_course_title', 'Unknown Course')
        
        if not course_id:
            await update.message.reply_text(
                "❌ No course selected. Please use /batches to select a batch first."
            )
            return
        
        await update.message.reply_text(
            f"📡 Fetching data for: {course_title}\n"
            f"🎥 Using quality preference: {preferred_quality.upper()}"
        )
        
        await self.fetch_and_send_course_data(update, context, course_id, course_title, preferred_quality)
    
    async def fetch_and_send_course_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE, course_id: str, course_title: str, preferred_quality: str = None):
        """Fetch and process course data and send as file"""
        if preferred_quality is None:
            user_id = update.effective_user.id
            preferred_quality = self.user_preferences.get(user_id, "720p")
        
        try:
            api_url = f"{self.api_base_url}/courses/{course_id}/classes?populate=full"
            logger.info(f"Fetching course data from: {api_url}")
            
            response = requests.get(api_url, timeout=30)
            logger.info(f"Course API Response Status: {response.status_code}")
            
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Course API Response Keys: {list(data.keys())}")
            
            # Check if API returned success
            if data.get('state') != 200:
                error_msg = data.get('msg', 'Unknown error')
                logger.error(f"Course API returned error: {error_msg}")
                await update.effective_message.reply_text(f"❌ API Error: {error_msg}")
                return
            
            # Check if data structure is as expected
            if 'data' not in data:
                logger.error(f"Unexpected data structure: {data}")
                await update.effective_message.reply_text("❌ Unexpected data format from API.")
                return
            
            course_info = data['data'].get('course', {})
            classes_data = data['data'].get('classes', [])
            
            logger.info(f"Found {len(classes_data)} topics in course")
            
            if not classes_data:
                await update.effective_message.reply_text("❌ No class data found for this course.")
                return
            
            text_content = self.generate_formatted_text_file(course_info, classes_data, preferred_quality)
            
            filename = f"{course_title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            # Send as text file
            await update.effective_message.reply_document(
                document=text_content.encode('utf-8'),
                filename=filename,
                caption=(
                    f"📚 Course Data: {course_title}\n"
                    f"🎥 Quality Preference: {preferred_quality.upper()}\n"
                    f"📅 Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            )
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching course data: {e}")
            await update.effective_message.reply_text("❌ Network error fetching course data. Please try again later.")
        except ValueError as e:
            logger.error(f"JSON parsing error: {e}")
            await update.effective_message.reply_text("❌ Data format error from API. Please try again later.")
        except Exception as e:
            logger.error(f"Unexpected error in fetch_course_data: {e}")
            await update.effective_message.reply_text("❌ Error fetching course data. Please try again later.")
    
    def get_preferred_video_url(self, class_data, preferred_quality):
        """Get only the preferred quality video URL"""
        mp4_recordings = class_data.get('mp4Recordings', [])
        
        # If no recordings, try class_link
        if not mp4_recordings:
            class_link = class_data.get('class_link')
            if class_link and class_link.startswith(('http://', 'https://')):
                return class_link
            return None
        
        # Look for exact quality match first
        for recording in mp4_recordings:
            quality = recording.get('quality', '').lower()
            if quality == preferred_quality.lower():
                return recording.get('url')
        
        # If exact match not found, look for closest quality
        quality_priority = ['1080p', '720p', '480p', '360p', '240p']
        if preferred_quality.lower() in quality_priority:
            pref_index = quality_priority.index(preferred_quality.lower())
            for i in range(pref_index, len(quality_priority)):
                for recording in mp4_recordings:
                    if recording.get('quality', '').lower() == quality_priority[i]:
                        return recording.get('url')
        
        # If still not found, return the first available recording
        if mp4_recordings:
            return mp4_recordings[0].get('url')
        
        # Fallback to class_link
        class_link = class_data.get('class_link')
        if class_link and class_link.startswith(('http://', 'https://')):
            return class_link
        
        return None
    
    def generate_formatted_text_file(self, course_info, classes_data, preferred_quality):
        """Generate text file in the exact format you provided with PDFs below respective videos"""
        lines = []
        
        # Process all classes and organize by class number
        class_entries = {}
        pdf_entries = []
        
        for topic_index, topic in enumerate(classes_data, 1):
            topic_name = topic.get('topicName', f'Topic {topic_index}')
            topic_classes = topic.get('classes', [])
            
            for class_data in topic_classes:
                class_title = class_data.get('title', '')
                teacher_name = class_data.get('teacherName', 'Unknown Teacher')
                subject = topic_name
                
                # Extract class number from title or use default
                class_number = "01"
                if class_title:
                    # Try to extract number from title (e.g., "Class 01" or "Class-01")
                    import re
                    match = re.search(r'(\d+)', class_title)
                    if match:
                        class_number = match.group(1).zfill(2)
                
                # Get video URL with preferred quality only
                video_url = self.get_preferred_video_url(class_data, preferred_quality)
                
                if video_url:
                    # Format: Class-01 || English Basics | Aman Sir | English | (AMAN SIR): https://...
                    formatted_line = f"Class-{class_number} || {class_title} | {teacher_name} | {subject} | ({teacher_name.upper()}): {video_url}"
                    
                    # Store class entry
                    class_entries[class_number] = formatted_line
                    
                    # Get PDFs for this specific class and store them with the class number
                    class_pdfs = class_data.get('classPdf', [])
                    for pdf in class_pdfs:
                        pdf_url = pdf.get('url')
                        pdf_name = pdf.get('name', 'Unknown PDF')
                        if pdf_url and pdf_url.startswith(('http://', 'https://')):
                            pdf_line = f"{pdf_name} ({teacher_name.upper()}): {pdf_url}"
                            # Store PDF with reference to its class
                            if class_number not in class_entries:
                                class_entries[class_number] = None
                            # We'll associate PDFs with classes when building the final output
        
        # Now build the final output with videos and their respective PDFs
        final_lines = []
        
        # Sort classes by number
        sorted_classes = sorted(class_entries.keys())
        
        for class_num in sorted_classes:
            class_line = class_entries[class_num]
            if class_line:
                final_lines.append(class_line)
                
                # Add PDFs that belong to this class
                # Find PDFs for this class by matching class number in PDF name
                for topic in classes_data:
                    for class_data in topic.get('classes', []):
                        class_title = class_data.get('title', '')
                        teacher_name = class_data.get('teacherName', 'Unknown Teacher')
                        
                        # Check if this class matches our current class number
                        current_class_num_match = re.search(r'(\d+)', class_title) if class_title else None
                        current_class_num = current_class_num_match.group(1).zfill(2) if current_class_num_match else None
                        
                        if current_class_num == class_num:
                            class_pdfs = class_data.get('classPdf', [])
                            for pdf in class_pdfs:
                                pdf_url = pdf.get('url')
                                pdf_name = pdf.get('name', 'Unknown PDF')
                                if pdf_url and pdf_url.startswith(('http://', 'https://')):
                                    pdf_line = f"{pdf_name} ({teacher_name.upper()}): {pdf_url}"
                                    final_lines.append(pdf_line)
                
                final_lines.append("")  # Empty line between classes
        
        return '\n'.join(final_lines)
    
    async def quality_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [
                InlineKeyboardButton("240p", callback_data="quality_240p"),
                InlineKeyboardButton("360p", callback_data="quality_360p"),
                InlineKeyboardButton("480p", callback_data="quality_480p"),
            ],
            [
                InlineKeyboardButton("720p", callback_data="quality_720p"),
                InlineKeyboardButton("1080p", callback_data="quality_1080p"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎥 Select your preferred video quality:",
            reply_markup=reply_markup
        )
    
    async def quality_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        quality = query.data.replace("quality_", "")
        
        self.user_preferences[user_id] = quality
        await query.edit_message_text(
            f"✅ Video quality preference set to: {quality.upper()}"
        )
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        current_quality = self.user_preferences.get(user_id, "720p")
        
        await update.message.reply_text(
            f"👋 Available commands:\n\n"
            f"/start - Show welcome message\n"
            f"/help - Help & usage\n"
            f"/batches - Show all available batches\n"
            f"/quality - Change video quality (Current: {current_quality.upper()})\n"
            f"/get_course - Fetch data for selected batch"
        )

def run_flask():
    app.run(host='0.0.0.0', port=port)

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('BOT_TOKEN')
    
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN environment variable is required")
        logger.error("Please set TELEGRAM_BOT_TOKEN in your Render environment variables")
        return
    
    logger.info("✅ Bot token found, starting bot...")
    
    try:
        # Start Flask in a separate thread
        import threading
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        logger.info(f"🌐 Flask server started on port {port}")
        
        # Start the bot
        bot = CourseBot(token)
        logger.info("🤖 Bot is starting...")
        bot.application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

if __name__ == '__main__':
    main()
