import os
import logging
import threading
import time
import requests
from datetime import datetime
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Get port from environment variable (Render provides this)
port = int(os.environ.get('PORT', 5000))

# Initialize Flask app for keeping Render awake
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Telegram Course Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

def run_flask():
    app.run(host='0.0.0.0', port=port)

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
        self.user_preferences = {}  # Store user video quality preferences
        self.setup_handlers()
        
    def setup_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("get_course", self.get_course_command))
        self.application.add_handler(CommandHandler("quality", self.quality_command))
        self.application.add_handler(CallbackQueryHandler(self.quality_callback, pattern="^quality_"))
        # Handle any random text
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        # Set default quality preference
        if user_id not in self.user_preferences:
            self.user_preferences[user_id] = "720p"  # Default to 720p
        
        welcome_text = f"""
🤖 **Course Data Bot**

I can fetch course data from the API and send you a **formatted text file** containing:

- Topics and classes
- Video lecture links (your chosen quality)
- PDF material links
- Teacher information

**Your current video quality preference:** `{self.user_preferences[user_id]}`

**Commands:**
/start - Show this message  
/help - Get help information  
/quality - Change video quality preference  
/get_course - Fetch course data from API and get a text file
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = """
📖 **Help Guide**

**/get_course**  
- Fetches data from the course API  
- Generates a **.txt file** with:
  - Course info
  - Topics and classes
  - Video links (your preferred quality)
  - PDF links with names

**/quality**  
- Change your preferred video quality  
- Available options: 240p, 360p, 480p, 720p, 1080p  
- The bot will prioritize your chosen quality

The bot generates a structured text file with all the links.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def quality_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Let user choose video quality preference."""
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
            "🎥 **Select your preferred video quality:**\n\n"
            "This will determine which video links are shown first in the generated file. "
            "If your chosen quality isn't available, other qualities will be shown.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def quality_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quality selection."""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        quality = query.data.replace("quality_", "")
        
        if quality == "all":
            self.user_preferences[user_id] = "all"
            await query.edit_message_text(
                "✅ **Video quality preference set to: All Qualities**\n\n"
                "All available video qualities will be shown in the generated file.",
                parse_mode='Markdown'
            )
        else:
            self.user_preferences[user_id] = quality
            await query.edit_message_text(
                f"✅ **Video quality preference set to: {quality.upper()}**\n\n"
                f"This quality will be prioritized in the generated file.",
                parse_mode='Markdown'
            )
    
    async def get_course_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetch course data from API and generate text file."""
        user_id = update.effective_user.id
        
        # Get user's quality preference
        preferred_quality = self.user_preferences.get(user_id, "720p")
        
        await update.message.reply_text(
            f"📡 Fetching course data from API...\n"
            f"🎥 Using quality preference: **{preferred_quality.upper()}**",
            parse_mode='Markdown'
        )

        try:
            # You can change the course ID here or later make it dynamic
            course_id = "68e7b6e6aaf4383d1192dfb6"
            api_url = f"{self.api_base_url}/courses/{course_id}/classes?populate=full"
            
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('state') != 200:
                await update.message.reply_text("❌ Failed to fetch course data from API.")
                return
            
            course_info = data['data']['course']
            classes_data = data['data']['classes']
            
            # Generate text file content with user's quality preference
            text_content = self.generate_course_text_file(course_info, classes_data, preferred_quality)
            
            # Send as text file
            filename = f"course_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            await update.message.reply_document(
                document=text_content.encode('utf-8'),
                filename=filename,
                caption=(
                    f"📚 Course Data: {course_info.get('title', 'Unknown Course')}\n"
                    f"🎥 Quality Preference: {preferred_quality.upper()}\n"
                    f"📅 Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            )
            
            await update.message.reply_text("✅ Course data file generated successfully!")
            
        except Exception as e:
            logger.error(f"Error fetching course data: {e}")
            await update.message.reply_text("❌ Error fetching course data. Please try again later.")
    
    def get_video_links_by_preference(self, class_data, preferred_quality):
        """Get video links sorted by user's quality preference."""
        video_links = []
        
        # Get class link (usually the main video)
        class_link = class_data.get('class_link')
        if class_link and class_link.startswith(('http://', 'https://')):
            video_links.append({"url": class_link, "quality": "Main Link", "is_preferred": False})
        
        # Get MP4 recordings
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
        
        # Sort videos: preferred quality first, then others
        if preferred_quality != "all":
            video_links.sort(key=lambda x: (not x["is_preferred"], x["quality"]))
        
        return video_links
    
    def generate_course_text_file(self, course_info, classes_data, preferred_quality):
        """Generate formatted text file with course data (videos + PDFs)."""
        lines = []
        
        # Header
        lines.append(f"Course Data Extracted on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Source: {course_info.get('title', 'Unknown Course')}")
        lines.append(f"Video Quality Preference: {preferred_quality.upper()}")
        lines.append("=" * 50)
        lines.append("")
        
        # Process each topic
        for topic_index, topic in enumerate(classes_data, 1):
            topic_name = topic.get('topicName', f'Topic {topic_index}')
            topic_classes = topic.get('classes', [])
            
            lines.append(f"TOPIC: {topic_name}")
            lines.append("-" * 30)
            lines.append("")
            
            # Process each class in the topic
            for class_index, class_data in enumerate(topic_classes, 1):
                class_title = class_data.get('title', f'Class {class_index}')
                class_description = class_data.get('description', '')
                teacher_name = class_data.get('teacherName', 'Unknown Teacher')
                
                # Class header
                lines.append(f"Class {class_index}: {class_title}")
                if class_description:
                    lines.append(f"Description: {class_description}")
                lines.append(f"Teacher: {teacher_name}")
                lines.append("")
                
                # Video links with quality preference
                video_links = self.get_video_links_by_preference(class_data, preferred_quality)
                
                if video_links:
                    lines.append("Video Lectures:")
                    preferred_found = any(link["is_preferred"] for link in video_links)
                    
                    if preferred_quality != "all" and preferred_found:
                        lines.append(f"  🎥 **Preferred Quality ({preferred_quality.upper()}):**")
                        for link in video_links:
                            if link["is_preferred"]:
                                lines.append(f"    ✓ {link['url']} (Quality: {link['quality']})")
                        lines.append("")
                        lines.append("  📹 Other Available Qualities:")
                        for link in video_links:
                            if not link["is_preferred"]:
                                lines.append(f"    • {link['url']} (Quality: {link['quality']})")
                    else:
                        for i, link in enumerate(video_links, 1):
                            prefix = "✓" if link["is_preferred"] else "•"
                            lines.append(f"  {prefix} {link['url']} (Quality: {link['quality']})")
                    lines.append("")
                
                # PDF links
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
        """Fallback for plain text messages."""
        user_id = update.effective_user.id
        current_quality = self.user_preferences.get(user_id, "720p")
        
        await update.message.reply_text(
            f"👋 I only support these commands right now:\n\n"
            f"/start - Show welcome message\n"
            f"/help - Help & usage\n"
            f"/quality - Change video quality (Current: {current_quality.upper()})\n"
            f"/get_course - Fetch course data from the API"
        )

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info(f"Flask server starting on port {port}")
    
    # Start the bot
    bot = CourseBot(token)
    
    logger.info("Bot is starting...")
    bot.application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
