# Copilot Instructions for Connor French's Quarto Website

## Project Overview
This is a personal academic website built with Quarto. It showcases posts, projects, presentations, and teaching materials.

## Logging
Always log your changes in logs/AI_UPDATES.md with a brief description of what you changed and why.  

## Website Structure
- **Root files**: Main `.qmd` files for top-level pages (about.qmd, index.qmd, posts.qmd, etc.)
- **Content directories**: 
  - `posts/` - Blog posts and tutorials
  - `projects/` - Research projects
  - `presentations/` - Slides and presentation materials
  - `teaching/` - Course and workshop information
- **Configuration**: `_quarto.yml` (main config), `_publish.yml` (deployment)
- **Styling**: `styles.scss` (SASS), `styles.css` (compiled CSS)

## Styling and Theme

### Theme Configuration
- **Light theme**: Minty with custom SCSS overrides
- **Dark theme**: Cyborg
- Both defined in `_quarto.yml` under `format.html.theme`

### Color Palette
```scss
$dark-blue: #224146  // Primary color
$orange: #CE6337     // Secondary color  
$yellow: #E3BA31     // Link color
$mustard: #9D8622    // Accent
```

### Styling Best Practices
1. Always maintain existing color scheme when adding new components
2. Use the color variables from `styles.scss` rather than hardcoding colors
3. Ensure both light and dark themes remain functional
4. Test any custom CSS against both themes
5. Keep custom styles in `styles.scss` for maintainability

## Creating New Content

### Blog Posts
1. Create a new directory in `posts/` with format: `YYYY-MM-DD-post-title/`
2. Add an `index.qmd` file in the directory
3. Include required YAML frontmatter:
   ```yaml
   ---
   title: "Your Post Title"
   description: "Brief description for listings"
   author: "Connor French"
   date: "YYYY-MM-DD"
   categories: [category1, category2]
   image: "optional-preview-image.jpg"
   draft: false  # Set to true while working
   ---
   ```
4. The `posts/_metadata.yml` provides defaults (title-block-banner, toc, etc.)

### Projects
1. Create a new directory in `projects/` with a descriptive name
2. Add an `index.qmd` file
3. Include frontmatter similar to posts
4. Consider adding a featured image for the project card

### Presentations
1. Store presentations in `presentations/` with date prefix: `YYYY-MM-DD_topic/`
2. Use Quarto's RevealJS format for slideshows when possible
3. Include frontmatter with title, date, and description

## Python Notebooks and Data Analysis

### Required Setup
When creating analytical notebooks or posts with Python code:

1. **Use Python with Polars** for all data frame operations
2. **Use Pixi** for environment management
3. **Standard imports**:
   ```python
   import polars as pl
   import numpy as np
   import seaborn as sns
   import altair as alt
   # Add other libraries as needed
   ```

### Python Environment
- **Use Pixi** as the environment manager for all Python notebooks
- Create/update `pixi.toml` in the project root for dependencies
- Initialize a new project with: `pixi init`
- Add dependencies with: `pixi add package-name`
- Core dependencies for analytical work:
  - `polars` (data frame operations)
  - `numpy` (numerical operations)
  - `seaborn` (non-interactive visualization)
  - `altair` (interactive visualization)
  - `scikit-learn` (machine learning, if needed)
  - `jupyter` (notebook support)

### Notebook Best Practices
1. **Execution options** (already set in `posts/_metadata.yml`):
   ```yaml
   execute:
     echo: true      # Show code
     message: true   # Show messages
     warning: true   # Show warnings
   ```
2. **Code style**:
   - Use descriptive variable names
   - Add comments for complex operations
   - Break long pipelines into readable chunks
   - Use Polars' method chaining for clarity
3. **Output management**:
   - Use `freeze: auto` (already set) to cache expensive computations
   - Store large data files in appropriate directories, not in git
   - Consider using relative paths for reproducibility
4. **Visualization**:
   - **Use Altair** for interactive visualizations (default)
   - **Use Seaborn** for non-interactive/static plots
   - Ensure plots use website color scheme when appropriate:
     - Primary: `#224146` (dark-blue)
     - Secondary: `#CE6337` (orange)
     - Accent: `#E3BA31` (yellow)
   - Add clear titles, labels, and legends
   - Make plots readable in both light and dark themes
   - Set Altair theme to match website aesthetics

### Polars-Specific Guidelines
```python
# Prefer Polars expressions over pandas-style operations
df = pl.read_csv("data.csv")

# Use method chaining
result = (
    df
    .filter(pl.col("column") > threshold)
    .group_by("category")
    .agg([
        pl.col("value").mean().alias("mean_value"),
        pl.col("value").count().alias("count")
    ])
    .sort("mean_value", descending=True)
)

# Use lazy evaluation for large datasets
df_lazy = pl.scan_csv("large_data.csv")
result = df_lazy.filter(...).collect()
```

### Visualization Guidelines

#### Interactive Plots with Altair
```python
import altair as alt

# Configure custom theme with website colors
alt.themes.enable('default')

# Create interactive chart
chart = alt.Chart(df).mark_point().encode(
    x='column1:Q',
    y='column2:Q',
    color=alt.Color('category:N', scale=alt.Scale(
        range=['#224146', '#CE6337', '#E3BA31', '#9D8622']
    )),
    tooltip=['column1', 'column2', 'category']
).properties(
    width=600,
    height=400,
    title='Chart Title'
).interactive()

chart.display()
```

#### Static Plots with Seaborn
```python
import seaborn as sns
import matplotlib.pyplot as plt

# Use website color palette
website_colors = ['#224146', '#CE6337', '#E3BA31', '#9D8622']
sns.set_palette(website_colors)
sns.set_style('whitegrid')

# Create plot
fig, ax = plt.subplots(figsize=(10, 6))
sns.scatterplot(data=df, x='column1', y='column2', hue='category', ax=ax)
ax.set_title('Chart Title', fontsize=14)
ax.set_xlabel('X Label', fontsize=12)
ax.set_ylabel('Y Label', fontsize=12)
plt.tight_layout()
plt.show()
```

## File Organization

### Best Practices
1. Keep related files together in their respective directories
2. Use meaningful, lowercase directory names with hyphens (kebab-case)
3. Include README or description in project directories when helpful
4. Store static assets (images, data files) in appropriate subdirectories
5. Use the `static/` directory for files that should be copied as-is to `_site/`

### Assets and Resources
- **Images**: Store in the same directory as the post/project using them
- **Data files**: Consider using `files/` directory or post-specific subdirectories
- **PDFs/Publications**: Use `files/publications/`
- **Large files**: Don't commit to git; use external storage and download scripts

## Quarto-Specific Best Practices

### Configuration
1. Site-wide settings go in `_quarto.yml`
2. Section-specific settings go in `_metadata.yml` files (e.g., `posts/_metadata.yml`)
3. Document-specific settings go in YAML frontmatter

### Building and Previewing
```bash
# Preview the site locally
quarto preview

# Render the entire site
quarto render

# Render a specific document
quarto render path/to/file.qmd
```

### Extensions
- The site uses Font Awesome extension (in `_extensions/`)
- Use Font Awesome icons with: `{{< fa icon-name >}}`
- Use embedio extension for embedding content

### Cross-References
- Use Quarto's cross-reference syntax for figures, tables, equations
- Example: `@fig-plot`, `@tbl-results`, `@eq-model`

## Version Control

### Git Workflow
1. Don't commit `_site/` directory (should be in `.gitignore`)
2. Don't commit large data files or outputs
3. Use meaningful commit messages
4. Consider using branches for major changes

### Freeze Directory
- `_freeze/` contains cached computational outputs
- Typically should be committed to avoid re-running expensive computations
- Can be regenerated if needed with `quarto render --cache-refresh`

## Common Tasks

### Adding a New Blog Post
```bash
# 1. Create directory
mkdir posts/$(date +%Y-%m-%d)-my-new-post
cd posts/$(date +%Y-%m-%d)-my-new-post

# 2. Create index.qmd with frontmatter
# 3. Write content
# 4. Preview: quarto preview
# 5. Commit and push
```

### Updating Styles
1. Edit `styles.scss` (SCSS variables and rules)
2. Preview changes with `quarto preview`
3. Commit both `styles.scss` and compiled `styles.css`

### Managing Python Environment with Pixi
```bash
# Initialize a new Pixi project
pixi init

# Add dependencies
pixi add polars numpy seaborn altair jupyter

# Install all dependencies
pixi install

# Run a Python script or notebook
pixi run python script.py
pixi run jupyter notebook

# Update dependencies
pixi update
```

### Adding Interactive Elements
- Use Quarto's built-in support for interactive widgets
- Consider ObservableJS for interactive JavaScript
- Use Altair or other Python libraries for interactive plots
- Leverage Quarto's HTML output format capabilities

## Analytics and SEO
- Google Analytics is configured (ID in `_quarto.yml`)
- Each page should have meaningful title and description
- Use descriptive filenames and titles for better SEO
- Include alt text for images

## Accessibility
1. Use semantic HTML headers (h1, h2, h3) in proper order
2. Include alt text for all images
3. Ensure sufficient color contrast
4. Test with screen readers when possible
5. Use descriptive link text (avoid "click here")

## Comments
- Comments use Utterances (GitHub issues-based)
- Configuration in `posts/_metadata.yml`
- Requires visitors to have a GitHub account

## Deployment
- Deployment configuration in `_publish.yml`
- Site URL: https://connor-french.com
- Typically deploy via `quarto publish` or CI/CD

## When Modifying Code
1. Maintain consistency with existing style and structure
2. Test locally before committing
3. Update documentation if adding new features
4. Consider both mobile and desktop views
5. Ensure changes work with both light and dark themes
6. Use Python with Polars for any new data analysis code
