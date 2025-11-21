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
            
            await query.edit_message_text(f"✅ Selected: {course_title}\n\nFetching course data...")
            
            # Store selected course ID in context for get_course_command
            context.user_data['selected_course_id'] = course_id
            context.user_data['selected_course_title'] = course_title
            
            # Automatically fetch course data
            await self.fetch_course_data(update, context, course_id, course_title)
            
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
        
        await self.fetch_course_data(update, context, course_id, course_title, preferred_quality)
    
    async def fetch_course_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE, course_id: str, course_title: str, preferred_quality: str = None):
        """Fetch and process course data"""
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
                await update.message.reply_text(f"❌ API Error: {error_msg}")
                return
            
            # Check if data structure is as expected
            if 'data' not in data:
                logger.error(f"Unexpected data structure: {data}")
                await update.message.reply_text("❌ Unexpected data format from API.")
                return
            
            course_info = data['data'].get('course', {})
            classes_data = data['data'].get('classes', [])
            
            logger.info(f"Found {len(classes_data)} topics in course")
            
            if not classes_data:
                await update.message.reply_text("❌ No class data found for this course.")
                return
            
            text_content = self.generate_course_text_file(course_info, classes_data, preferred_quality)
            
            filename = f"{course_title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            # Send as text file
            await update.message.reply_document(
                document=text_content.encode('utf-8'),
                filename=filename,
                caption=(
                    f"📚 Course Data: {course_title}\n"
                    f"🎥 Quality Preference: {preferred_quality.upper()}\n"
                    f"📅 Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            )
            
            await update.message.reply_text("✅ Course data file generated successfully!")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching course data: {e}")
            await update.message.reply_text("❌ Network error fetching course data. Please try again later.")
        except ValueError as e:
            logger.error(f"JSON parsing error: {e}")
            await update.message.reply_text("❌ Data format error from API. Please try again later.")
        except Exception as e:
            logger.error(f"Unexpected error in fetch_course_data: {e}")
            await update.message.reply_text("❌ Error fetching course data. Please try again later.")
    
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
                InlineKeyboardButton("All Qualities", callback_data="quality_all"),
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
        
        if quality == "all":
            self.user_preferences[user_id] = "all"
            await query.edit_message_text(
                "✅ Video quality preference set to: All Qualities"
            )
        else:
            self.user_preferences[user_id] = quality
            await query.edit_message_text(
                f"✅ Video quality preference set to: {quality.upper()}"
            )
    
    def get_video_links_by_preference(self, class_data, preferred_quality):
        video_links = []
        
        class_link = class_data.get('class_link')
        if class_link and class_link.startswith(('http://', 'https://')):
            video_links.append({"url": class_link, "quality": "Main Link", "is_preferred": False})
        
        mp4_recordings = class_data.get('mp4Recordings', [])
        for recording in mp4_recordings:
            video_url = recording.get('url')
            quality = recording.get('quality', 'Unknown')
            if video_url and video_url.startswith(('http://', 'https://')):
                is_preferred = (preferred_quality != "all" and quality.lower() == preferred_quality.lower())
                video_links.append({
                    "url": video_url, 
                    "quality": quality, 
                    "is_preferred": is_preferred
                })
        
        if preferred_quality != "all":
            video_links.sort(key=lambda x: (not x["is_preferred"], x["quality"]))
        
        return video_links
    
    def generate_course_text_file(self, course_info, classes_data, preferred_quality):
        lines = []
        
        lines.append(f"Course Data Extracted on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Source: {course_info.get('title', 'Unknown Course')}")
        lines.append(f"Video Quality Preference: {preferred_quality.upper()}")
        lines.append("=" * 50)
        lines.append("")
        
        for topic_index, topic in enumerate(classes_data, 1):
            topic_name = topic.get('topicName', f'Topic {topic_index}')
            topic_classes = topic.get('classes', [])
            
            lines.append(f"TOPIC: {topic_name}")
            lines.append("-" * 30)
            lines.append("")
            
            for class_index, class_data in enumerate(topic_classes, 1):
                class_title = class_data.get('title', f'Class {class_index}')
                class_description = class_data.get('description', '')
                teacher_name = class_data.get('teacherName', 'Unknown Teacher')
                
                lines.append(f"Class {class_index}: {class_title}")
                if class_description:
                    lines.append(f"Description: {class_description}")
                lines.append(f"Teacher: {teacher_name}")
                lines.append("")
                
                video_links = self.get_video_links_by_preference(class_data, preferred_quality)
                
                if video_links:
                    lines.append("Video Lectures:")
                    preferred_found = any(link["is_preferred"] for link in video_links)
                    
                    if preferred_quality != "all" and preferred_found:
                        lines.append(f"  Preferred Quality ({preferred_quality.upper()}):")
                        for link in video_links:
                            if link["is_preferred"]:
                                lines.append(f"    ✓ {link['url']} (Quality: {link['quality']})")
                        lines.append("")
                        lines.append("  Other Available Qualities:")
                        for link in video_links:
                            if not link["is_preferred"]:
                                lines.append(f"    • {link['url']} (Quality: {link['quality']})")
                    else:
                        for i, link in enumerate(video_links, 1):
                            prefix = "✓" if link["is_preferred"] else "•"
                            lines.append(f"  {prefix} {link['url']} (Quality: {link['quality']})")
                    lines.append("")
                
                pdf_links = []
                class_pdfs = class_data.get('classPdf', [])
                for pdf in class_pdfs:
                    pdf_url = pdf.get('url')
                    pdf_name = pdf.get('name', 'Unknown PDF')
                    if pdf_url and pdf_url.startswith(('http://', 'https://')):
                        pdf_links.append(f"{pdf_url} (Name: {pdf_name})")
                
                if pdf_links:
                    lines.append("PDF Materials:")
                    for i, pdf_link in enumerate(pdf_links, 1):
                        lines.append(f"  {i}. {pdf_link}")
                    lines.append("")
                
                lines.append("=" * 50)
                lines.append("")
        
        return '\n'.join(lines)
    
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
