import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.sql.*;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import java.util.Set;
import java.util.HashSet;
import java.util.Arrays;
import java.util.stream.Collectors;

// Jaudiotagger imports
import org.jaudiotagger.audio.AudioFile;
import org.jaudiotagger.audio.AudioFileIO;
import org.jaudiotagger.audio.exceptions.CannotReadException;
import org.jaudiotagger.audio.exceptions.InvalidAudioFrameException;
import org.jaudiotagger.audio.exceptions.ReadOnlyFileException;
import org.jaudiotagger.tag.FieldKey;
import org.jaudiotagger.tag.TagException;

// Jackson imports for JSON
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

/**
 * Represents a single track match found during the scanning process.
 * Used to store details of a potential audio file for a compilation.
 */
class TrackMatch {
    public double score;
    public String path;
    public String filename;
    public double duration;
    public long size;
    public int bitrate;
    public String album;

    // Default constructor for Jackson deserialization
    public TrackMatch() {}

    /**
     * Constructs a new TrackMatch instance.
     * @param score The similarity score of the match.
     * @param path The full path to the audio file.
     * @param filename The filename of the audio file.
     * @param duration The duration of the audio file in seconds.
     * @param size The size of the audio file in bytes.
     * @param bitrate The bitrate of the audio file in kbps.
     * @param album The album name from the audio metadata.
     */
    public TrackMatch(double score, String path, String filename, double duration, long size, int bitrate, String album) {
        this.score = score;
        this.path = path;
        this.filename = filename;
        this.duration = duration;
        this.size = size;
        this.bitrate = bitrate;
        this.album = album;
    }

    @Override
    public String toString() {
        return String.format("Score: %.2f, Path: %s, Filename: %s, Duration: %.0f, Size: %d, Album: %s",
                score, path, filename, duration, size, album);
    }
}

/**
 * Functional interface for reporting compilation progress.
 */
@FunctionalInterface
interface ProgressCallback {
    /**
     * Called to report the current progress of the compilation process.
     * @param current The current item being processed.
     * @param total The total number of items to process.
     * @param status A descriptive string of the current operation.
     */
    void onProgress(int current, int total, String status);
}

/**
 * Functional interface for allowing user choice when multiple track versions are found.
 */
@FunctionalInterface
interface ChoiceCallback {
    /**
     * Called when multiple matches are found for a track, allowing the user to select one.
     * @param artist The artist of the track.
     * @param title The title of the track.
     * @param matches A list of potential TrackMatch objects.
     * @return The path of the selected track, or null if no selection is made.
     */
    String onChoice(String artist, String title, List<TrackMatch> matches);
}

/**
 * Main class for creating music compilations.
 * It interacts with an SQLite database (music_library.db) and the file system.
 */
public class CompilationCreator {

    // CONFIGURATION
    private static final String DB_PATH = "music_library.db";
    private static final String SECOND_FOLDER = "/Volumes/Incoming";
    private static final String COMPILATIONS_FILE = "compilations.json";

    // Accepted audio file extensions for scanning the second folder
    private static final Set<String> ACCEPTED_EXTENSIONS = new HashSet<>(Arrays.asList(
            ".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a"
    ));

    private Connection conn;
    private ObjectMapper objectMapper; // Jackson object mapper for JSON

    /**
     * Constructs a new CompilationCreator instance.
     * Initializes the database connection and the Jackson ObjectMapper.
     */
    public CompilationCreator() {
        try {
            // Load the SQLite JDBC driver
            Class.forName("org.sqlite.JDBC");
            conn = DriverManager.getConnection("jdbc:sqlite:" + DB_PATH);
            // Ensure the MusicScanner has created the 'tracks' table or create it if not
            createTracksTableIfNotExists();
        } catch (ClassNotFoundException e) {
            System.err.println("Error: SQLite JDBC driver not found. Make sure the JAR is in your classpath.");
            System.err.println(e.getMessage());
            // Exit if critical dependency is missing
            System.exit(1);
        } catch (SQLException e) {
            System.err.println("Error connecting to database: " + e.getMessage());
            // Exit if critical database connection fails
            System.exit(1);
        }

        objectMapper = new ObjectMapper();
        // Pretty print JSON for readability
        objectMapper.enable(SerializationFeature.INDENT_OUTPUT);
    }

    /**
     * Ensures the 'tracks' table exists in the database.
     * This is a safeguard if MusicScanner hasn't been run yet.
     */
    private void createTracksTableIfNotExists() throws SQLException {
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
    }

    /**
     * Loads compilation data from the JSON file.
     * @return A list of maps, where each map represents a compilation.
     */
    public List<Map<String, Object>> loadCompilations() {
        File compilationsFile = new File(COMPILATIONS_FILE);
        if (compilationsFile.exists()) {
            try {
                // Read the JSON file and convert it to a List of Maps
                return objectMapper.readValue(compilationsFile,
                        objectMapper.getTypeFactory().constructCollectionType(List.class, Map.class));
            } catch (IOException e) {
                System.err.println("Error loading compilations from " + COMPILATIONS_FILE + ": " + e.getMessage());
            }
        }
        return new ArrayList<>();
    }

    /**
     * Saves compilation data to the JSON file.
     * @param compilations The list of compilations to save.
     */
    public void saveCompilations(List<Map<String, Object>> compilations) {
        try {
            // Write the List of Maps to the JSON file
            objectMapper.writeValue(new File(COMPILATIONS_FILE), compilations);
        } catch (IOException e) {
            System.err.println("Error saving compilations to " + COMPILATIONS_FILE + ": " + e.getMessage());
        }
    }

    /**
     * Normalizes a string by converting to lowercase, replacing specific characters,
     * removing diacritics, and trimming whitespace.
     * This helps in consistent string comparison for matching.
     * @param s The input string to normalize.
     * @return The normalized string.
     */
    private String normalize(String s) {
        if (s == null) {
            return "";
        }
        s = s.toLowerCase()
             .replace("’", "'")
             .replace("`", "'")
             .replace("‘", "'")
             .replace("-", " ")
             .replace("_", " ")
             .trim();
        // Normalize Unicode characters (e.g., é -> e)
        s = Normalizer.normalize(s, Normalizer.Form.NFKD);
        // Remove combining diacritical marks
        s = s.replaceAll("\\p{M}", "");
        return s;
    }

    /**
     * Calculates a simple similarity ratio between two normalized strings.
     * This is a basic implementation to mimic Python's difflib.SequenceMatcher.ratio().
     * It checks if one string contains the other, or calculates a ratio based on common characters.
     * @param s1 The first normalized string.
     * @param s2 The second normalized string.
     * @return A double representing the similarity ratio (0.0 to 1.0).
     */
    private double calculateSimilarityRatio(String s1, String s2) {
        if (s1.equals(s2)) {
            return 1.0;
        }
        if (s1.isEmpty() || s2.isEmpty()) {
            return 0.0;
        }

        // Check for substring containment for higher scores
        if (s1.contains(s2) || s2.contains(s1)) {
            return 0.9 + (double) Math.min(s1.length(), s2.length()) / Math.max(s1.length(), s2.length()) * 0.1; // Give a high score
        }

        // Fallback to a simpler character-based similarity
        int commonChars = 0;
        Set<Character> s1Chars = s1.chars().mapToObj(c -> (char) c).collect(Collectors.toSet());
        Set<Character> s2Chars = s2.chars().mapToObj(c -> (char) c).collect(Collectors.toSet());

        Set<Character> intersection = new HashSet<>(s1Chars);
        intersection.retainAll(s2Chars);
        commonChars = intersection.size();

        // Jaccard index for character sets
        return (double) commonChars / (s1Chars.size() + s2Chars.size() - commonChars);
    }


    /**
     * Finds all matching tracks in the database based on artist and title.
     * @param artist The artist to search for.
     * @param title The title to search for.
     * @return A list of TrackMatch objects.
     */
    public List<TrackMatch> findMatchesDb(String artist, String title) {
        List<TrackMatch> candidates = new ArrayList<>();
        String normalizedArtist = normalize(artist);
        String normalizedTitle = normalize(title);

        String sql = "SELECT path, filename, duration, size, bitrate, album FROM tracks";
        try (Statement stmt = conn.createStatement();
             ResultSet rs = stmt.executeQuery(sql)) {

            while (rs.next()) {
                String path = rs.getString("path");
                String filename = rs.getString("filename");
                double duration = rs.getDouble("duration");
                long size = rs.getLong("size");
                int bitrate = rs.getInt("bitrate");
                String album = rs.getString("album");

                String normalizedFilename = normalize(filename);

                // Check if normalized artist and title are present in normalized filename
                if (normalizedFilename.contains(normalizedArtist) && normalizedFilename.contains(normalizedTitle)) {
                    double score = calculateSimilarityRatio(normalizedTitle, normalizedFilename);
                    candidates.add(new TrackMatch(score, path, filename, duration, size, bitrate, album));
                }
            }
        } catch (SQLException e) {
            System.err.println("Database error during search: " + e.getMessage());
        }

        // Sort candidates by score (descending) and then by size (descending)
        candidates.sort(Comparator
                .comparingDouble(TrackMatch::score).reversed()
                .thenComparingLong(TrackMatch::size).reversed());

        return candidates;
    }

    /**
     * Finds all matching tracks in a given folder (e.g., SECOND_FOLDER) based on artist and title.
     * Extracts metadata using Jaudiotagger.
     * @param folderPath The path to the folder to scan.
     * @param artist The artist to search for.
     * @param title The title to search for.
     * @return A list of TrackMatch objects.
     */
    public List<TrackMatch> findMatchesFolder(String folderPath, String artist, String title) {
        List<TrackMatch> matches = new ArrayList<>();
        Path startPath = Paths.get(folderPath);

        if (!Files.exists(startPath) || !Files.isDirectory(startPath)) {
            System.err.println("Warning: Second folder does not exist or is not a directory: " + folderPath);
            return matches;
        }

        String normalizedArtist = normalize(artist);
        String normalizedTitle = normalize(title);

        try {
            Files.walk(startPath)
                 .filter(Files::isRegularFile)
                 .forEach(filePath -> {
                     String filename = filePath.getFileName().toString();
                     String normalizedFilename = normalize(filename);

                     String ext = "";
                     int dotIndex = filename.lastIndexOf('.');
                     if (dotIndex > 0 && dotIndex < filename.length() - 1) {
                         ext = filename.substring(dotIndex).toLowerCase();
                     }

                     if (!ACCEPTED_EXTENSIONS.contains(ext)) {
                         return; // Skip non-audio files
                     }

                     if (normalizedFilename.contains(normalizedArtist) && normalizedFilename.contains(normalizedTitle)) {
                         double duration = 0;
                         int bitrate = 0;
                         String album = "";

                         try {
                             File file = filePath.toFile();
                             AudioFile audioFile = AudioFileIO.read(file);
                             if (audioFile != null && audioFile.getAudioHeader() != null) {
                                 duration = audioFile.getAudioHeader().getTrackLength();
                                 bitrate = audioFile.getAudioHeader().getBitRateAsNumber();
                             }
                             if (audioFile != null && audioFile.getTag() != null) {
                                 album = audioFile.getTag().getFirst(FieldKey.ALBUM);
                                 if (album == null) {
                                     album = "";
                                 }
                             }
                         } catch (CannotReadException | IOException | TagException | ReadOnlyFileException | InvalidAudioFrameException e) {
                             System.err.println("Warning: Could not read audio metadata for " + filename + ": " + e.getMessage());
                         }
                         double score = calculateSimilarityRatio(normalizedTitle, normalizedFilename);
                         matches.add(new TrackMatch(score, filePath.toString(), filename, duration, filePath.toFile().length(), bitrate, album));
                     }
                 });
        } catch (IOException e) {
            System.err.println("Error during second folder traversal: " + e.getMessage());
        }

        // Sort candidates by score (descending) and then by size (descending)
        matches.sort(Comparator
                .comparingDouble(TrackMatch::score).reversed()
                .thenComparingLong(TrackMatch::size).reversed());

        return matches;
    }

    /**
     * Creates a compilation by finding and copying tracks to a new folder.
     * @param destBase The base destination folder where the compilation folder will be created.
     * @param compilationName The name of the compilation (will be the folder name).
     * @param tracklist A list of String arrays, where each inner array is [artist, title].
     * @param progressCallback An optional callback for reporting progress to a GUI.
     * @param choiceCallback An optional callback for user choice when multiple matches are found.
     * @return A list of three lists: notFoundTracks, notCopiedTracks, selectedPaths.
     */
    public List<List<String>> runCompilationProcess(
            String destBase,
            String compilationName,
            List<String[]> tracklist, // List of String[] where [0] is artist, [1] is title
            ProgressCallback progressCallback,
            ChoiceCallback choiceCallback) {

        Path destFolder = Paths.get(destBase, compilationName);
        try {
            Files.createDirectories(destFolder);
        } catch (IOException e) {
            System.err.println("Error creating destination folder: " + destFolder + " - " + e.getMessage());
            return Arrays.asList(new ArrayList<>(), new ArrayList<>(), new ArrayList<>());
        }

        List<String> notFoundTracks = new ArrayList<>();
        List<String> notCopiedTracks = new ArrayList<>();
        List<String> selectedPaths = new ArrayList<>(); // To return the paths of selected files

        List<Map<String, Object>> allFoundMatches = new ArrayList<>(); // (index, artist, title, matches)

        // Phase 1: Search for tracks
        if (progressCallback != null) {
            progressCallback.onProgress(0, tracklist.size(), "Searching for tracks...");
        }

        for (int i = 0; i < tracklist.size(); i++) {
            String[] track = tracklist.get(i);
            String artist = track[0];
            String title = track[1];

            if (progressCallback != null) {
                progressCallback.onProgress(i + 1, tracklist.size(), "Searching: " + artist + " - " + title);
            }

            List<TrackMatch> matches = findMatchesDb(artist, title);
            if (matches.isEmpty()) {
                matches = findMatchesFolder(SECOND_FOLDER, artist, title);
            }

            if (!matches.isEmpty()) {
                Map<String, Object> foundMatch = new HashMap<>();
                foundMatch.put("index", i + 1);
                foundMatch.put("artist", artist);
                foundMatch.put("title", title);
                foundMatch.put("matches", matches);
                allFoundMatches.add(foundMatch);
            } else {
                notFoundTracks.add(artist + " - " + title);
            }
        }

        // Phase 2: Select version (if necessary)
        List<Map.Entry<String, String>> tracksToCopy = new ArrayList<>(); // (srcPath, destPath)

        for (Map<String, Object> foundMatch : allFoundMatches) {
            int index = (int) foundMatch.get("index");
            String artist = (String) foundMatch.get("artist");
            String title = (String) foundMatch.get("title");
            @SuppressWarnings("unchecked")
            List<TrackMatch> matches = (List<TrackMatch>) foundMatch.get("matches");

            String selectedPath = null;
            if (matches.size() == 1) {
                selectedPath = matches.get(0).path;
            } else if (choiceCallback != null) {
                selectedPath = choiceCallback.onChoice(artist, title, matches);
            } else {
                // Default to the highest scored match if no callback
                selectedPath = matches.get(0).path;
            }

            if (selectedPath != null) {
                selectedPaths.add(selectedPath); // Add selected path to the return list
                TrackMatch selectedMatch = matches.stream()
                        .filter(m -> m.path.equals(selectedPath))
                        .findFirst()
                        .orElse(null);

                if (selectedMatch != null) {
                    String ext = "";
                    int dotIndex = selectedMatch.filename.lastIndexOf('.');
                    if (dotIndex > 0 && dotIndex < selectedMatch.filename.length() - 1) {
                        ext = selectedMatch.filename.substring(dotIndex);
                    }
                    // Format new filename: "01. Artist - Title.ext"
                    String newName = String.format("%02d. %s - %s%s", index, artist, title, ext);
                    Path destPath = destFolder.resolve(newName);
                    tracksToCopy.add(Map.entry(selectedPath, destPath.toString()));
                }
            }
        }

        // Phase 3: Copy files
        if (progressCallback != null) {
            progressCallback.onProgress(0, tracksToCopy.size(), "Copying files...");
        }

        for (int i = 0; i < tracksToCopy.size(); i++) {
            Map.Entry<String, String> entry = tracksToCopy.get(i);
            Path src = Paths.get(entry.getKey());
            Path dst = Paths.get(entry.getValue());

            if (progressCallback != null) {
                progressCallback.onProgress(i + 1, tracksToCopy.size(), "Copying: " + dst.getFileName());
            }

            try {
                // Use REPLACE_EXISTING to overwrite if file already exists
                Files.copy(src, dst, StandardCopyOption.REPLACE_EXISTING);
            } catch (IOException e) {
                notCopiedTracks.add(dst.getFileName().toString() + " (Error: " + e.getMessage() + ")");
                System.err.println("Error copying file " + src + " to " + dst + ": " + e.getMessage());
            }
        }

        // Phase 4: Write tracklist
        Path tracklistPath = destFolder.resolve("tracklist.txt");
        try {
            List<String> lines = new ArrayList<>();
            for (int i = 0; i < tracklist.size(); i++) {
                String[] track = tracklist.get(i);
                lines.add(String.format("%d. %s - %s", i + 1, track[0], track[1]));
            }
            Files.write(tracklistPath, lines);
        } catch (IOException e) {
            System.err.println("Error writing tracklist file: " + e.getMessage());
        }

        // Close the database connection when done
        try {
            if (conn != null) {
                conn.close();
            }
        } catch (SQLException e) {
            System.err.println("Error closing database connection: " + e.getMessage());
        }

        return Arrays.asList(notFoundTracks, notCopiedTracks, selectedPaths);
    }

    public static void main(String[] args) {
        // This module provides logic functions. Use it via a GUI or another main application.
        System.out.println("This module provides logic functions. Use it via a GUI or another main application.");

        // Example Usage (for testing purposes, uncomment to run a simple test)
        /*
        CompilationCreator creator = new CompilationCreator();

        // Example tracklist
        List<String[]> tracklist = new ArrayList<>();
        tracklist.add(new String[]{"Artist One", "Song One"});
        tracklist.add(new String[]{"Artist Two", "Song Two"});
        tracklist.add(new String[]{"Non Existent Artist", "Non Existent Song"});

        String destBase = "C:\\Temp\\Compilations"; // Or "/tmp/Compilations" on Linux/macOS
        String compilationName = "My Awesome Compilation";

        // Simple Progress Callback
        ProgressCallback simpleProgress = (current, total, status) ->
            System.out.printf("Progress: %d/%d - %s%n", current, total, status);

        // Simple Choice Callback (always picks the first match)
        ChoiceCallback simpleChoice = (artist, title, matches) -> {
            System.out.println("Multiple matches for " + artist + " - " + title + ":");
            for (int i = 0; i < matches.size(); i++) {
                System.out.println("  " + (i + 1) + ". " + matches.get(i).filename + " (Score: " + matches.get(i).score + ")");
            }
            // For a real GUI, this would prompt the user. Here, we just pick the first.
            return matches.get(0).path;
        };

        System.out.println("\n--- Starting Compilation Process ---");
        List<List<String>> results = creator.runCompilationProcess(
                destBase, compilationName, tracklist, simpleProgress, simpleChoice);

        List<String> notFound = results.get(0);
        List<String> notCopied = results.get(1);
        List<String> selected = results.get(2);

        System.out.println("\n--- Compilation Results ---");
        if (!notFound.isEmpty()) {
            System.out.println("Tracks not found: " + notFound);
        }
        if (!notCopied.isEmpty()) {
            System.out.println("Tracks not copied (errors): " + notCopied);
        }
        if (!selected.isEmpty()) {
            System.out.println("Selected track paths: " + selected);
        }
        System.out.println("Compilation created at: " + Paths.get(destBase, compilationName).toAbsolutePath());
        */
    }
}
