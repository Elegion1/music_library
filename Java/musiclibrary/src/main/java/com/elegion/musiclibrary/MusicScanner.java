import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.sql.*;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

// Jaudiotagger imports
import org.jaudiotagger.audio.AudioFile;
import org.jaudiotagger.audio.AudioFileIO;
import org.jaudiotagger.audio.exceptions.CannotReadException;
import org.jaudiotagger.audio.exceptions.InvalidAudioFrameException;
import org.jaudiotagger.audio.exceptions.ReadOnlyFileException;
import org.jaudiotagger.tag.FieldKey;
import org.jaudiotagger.tag.TagException;

public class MusicScanner {

    // CONFIGURATION
    private static final String DEFAULT_MUSIC_FOLDER = "/Volumes/NAS/Storage/Backup/Music";
    private static final String DB_PATH = "music_library.db";
    private static final Set<String> ACCEPTED_EXTENSIONS = new HashSet<>(Arrays.asList(
            ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a"
    ));
    private static final Set<String> EXCLUDE_KEYWORDS = new HashSet<>(Arrays.asList(
            // "remix", "live", "edit", "version", "karaoke", "instrumental", "demo", "acoustic"
    ));

    private Connection conn;
    private int updatedCount = 0;
    private int skippedCount = 0;
    private int addedCount = 0;

    public MusicScanner() {
        try {
            // Load the SQLite JDBC driver
            Class.forName("org.sqlite.JDBC");
            conn = DriverManager.getConnection("jdbc:sqlite:" + DB_PATH);
            createTable();
        } catch (ClassNotFoundException e) {
            System.err.println("Error: SQLite JDBC driver not found. Make sure the JAR is in your classpath.");
            System.err.println(e.getMessage());
            System.exit(1);
        } catch (SQLException e) {
            System.err.println("Error connecting to database: " + e.getMessage());
            System.exit(1);
        }
    }

    /**
     * Creates the 'tracks' table in the SQLite database if it doesn't already exist.
     */
    private void createTable() throws SQLException {
        String sql = """
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                filename TEXT,
                ext TEXT,
                size INTEGER,
                duration REAL,
                bitrate INTEGER,
                album TEXT,
                mtime REAL
            )
            """;
        try (Statement stmt = conn.createStatement()) {
            stmt.execute(sql);
        }
        System.out.println("Database table 'tracks' ensured.");
    }

    /**
     * Scans the specified music folder for audio files, extracts their metadata,
     * and updates/adds them to the database.
     *
     * @param musicFolderPath The path to the music folder to scan.
     */
    public void scanMusicFolder(String musicFolderPath) {
        System.out.println("\n🔍 Scanning library at: " + musicFolderPath);
        Path startPath = Paths.get(musicFolderPath);

        if (!Files.exists(startPath) || !Files.isDirectory(startPath)) {
            System.err.println("Error: Music folder does not exist or is not a directory: " + musicFolderPath);
            return;
        }

        try {
            Files.walk(startPath)
                 .filter(Files::isRegularFile)
                 .forEach(this::processFile);
        } catch (IOException e) {
            System.err.println("Error during folder traversal: " + e.getMessage());
        } finally {
            try {
                if (conn != null) {
                    conn.close();
                }
            } catch (SQLException e) {
                System.err.println("Error closing database connection: " + e.getMessage());
            }
        }

        System.out.println("\n✅ Indexing completed:");
        System.out.println("   New files added     : " + addedCount);
        System.out.println("   Files updated       : " + updatedCount);
        System.out.println("   Files skipped       : " + skippedCount);
    }

    /**
     * Processes a single file: checks its extension, keywords, and modification time,
     * then extracts metadata and updates/inserts into the database.
     *
     * @param filePath The path to the file to process.
     */
    private void processFile(Path filePath) {
        String fullPath = filePath.toString();
        File file = filePath.toFile();
        String filename = file.getName();
        String filenameLower = filename.toLowerCase();

        String ext = "";
        int dotIndex = filename.lastIndexOf('.');
        if (dotIndex > 0 && dotIndex < filename.length() - 1) {
            ext = filename.substring(dotIndex).toLowerCase();
        }

        // Check accepted extensions
        if (!ACCEPTED_EXTENSIONS.contains(ext)) {
            return;
        }

        // Check exclude keywords
        for (String keyword : EXCLUDE_KEYWORDS) {
            if (filenameLower.contains(keyword)) {
                return;
            }
        }

        long mtimeMillis = file.lastModified();
        double mtime = (double) mtimeMillis / 1000.0; // Convert to seconds for consistency with Python's os.stat().st_mtime
        long size = file.length();

        try {
            // Check if present in DB and if modified
            PreparedStatement selectStmt = conn.prepareStatement("SELECT mtime FROM tracks WHERE path = ?");
            selectStmt.setString(1, fullPath);
            ResultSet rs = selectStmt.executeQuery();

            if (rs.next()) {
                double dbMtime = rs.getDouble("mtime");
                // Compare with a small tolerance for floating point differences
                if (Math.abs(dbMtime - mtime) < 1.0) { // Less than 1 second difference
                    skippedCount++;
                    return; // Already indexed and not modified
                }
            }
            rs.close();
            selectStmt.close();

            // Extract audio metadata using Jaudiotagger
            double duration = 0;
            int bitrate = 0;
            String album = "";

            try {
                AudioFile audioFile = AudioFileIO.read(file);
                if (audioFile != null && audioFile.getAudioHeader() != null) {
                    duration = audioFile.getAudioHeader().getTrackLength();
                    bitrate = audioFile.getAudioHeader().getBitRateAsNumber();
                }
                if (audioFile != null && audioFile.getTag() != null) {
                    album = audioFile.getTag().getFirst(FieldKey.ALBUM);
                    if (album == null) {
                        album = ""; // Ensure album is not null
                    }
                }
            } catch (CannotReadException | IOException | TagException | ReadOnlyFileException | InvalidAudioFrameException e) {
                // Log the error but continue processing
                System.err.println("Warning: Could not read audio metadata for " + filename + ": " + e.getMessage());
            }

            // Prepare for insert or update
            if (rs.rowInserted() || rs.rowUpdated()) { // Check if row was found in previous select
                // Update existing record
                PreparedStatement updateStmt = conn.prepareStatement("""
                    UPDATE tracks SET filename=?, ext=?, size=?, duration=?, bitrate=?, album=?, mtime=? WHERE path=?
                    """);
                updateStmt.setString(1, filename);
                updateStmt.setString(2, ext);
                updateStmt.setLong(3, size);
                updateStmt.setDouble(4, duration);
                updateStmt.setInt(5, bitrate);
                updateStmt.setString(6, album);
                updateStmt.setDouble(7, mtime);
                updateStmt.setString(8, fullPath);
                updateStmt.executeUpdate();
                updateStmt.close();
                updatedCount++;
            } else {
                // Insert new record
                PreparedStatement insertStmt = conn.prepareStatement("""
                    INSERT INTO tracks (path, filename, ext, size, duration, bitrate, album, mtime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """);
                insertStmt.setString(1, fullPath);
                insertStmt.setString(2, filename);
                insertStmt.setString(3, ext);
                insertStmt.setLong(4, size);
                insertStmt.setDouble(5, duration);
                insertStmt.setInt(6, bitrate);
                insertStmt.setString(7, album);
                insertStmt.setDouble(8, mtime);
                insertStmt.executeUpdate();
                insertStmt.close();
                addedCount++;
            }
            conn.commit(); // Commit after each file for robustness, or batch for performance
        } catch (SQLException e) {
            System.err.println("Database error processing " + filename + ": " + e.getMessage());
            try {
                conn.rollback(); // Rollback on error
            } catch (SQLException rbEx) {
                System.err.println("Error during rollback: " + rbEx.getMessage());
            }
        }
    }

    public static void main(String[] args) {
        String musicFolder = DEFAULT_MUSIC_FOLDER;
        if (args.length > 0) {
            musicFolder = args[0];
        }

        MusicScanner scanner = new MusicScanner();
        scanner.scanMusicFolder(musicFolder);
    }
}
