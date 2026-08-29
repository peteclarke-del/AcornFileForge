window.AcornFormats = (() => {
  const imageExtensions = [
    "ssd", "dsd", "mmb", "uef", "hfe", "scp", "rom", "rom0", "rom1", "rom2", "rom3", "rom4", "rom5", "rom6", "rom7",
    "ads", "adm", "adl", "adf",
    "dat", "hdf", "hdd", "img", "raw", "bin", "dsk"
  ];
  const imagePattern = new RegExp(`\\.(${imageExtensions.join("|")})$`, "i");
  const dfsPattern = /\.(ssd|dsd|hfe|scp)$/i;
  const archivePattern = /\.zip$/i;
  const adfsPattern = /\.(ads|adm|adl|adf|dat|hdf|hdd|img|raw|bin|dsk|hfe|scp|zip)$/i;

  return {
    accept: imageExtensions.map(extension => `.${extension}`).concat(".dsc", ".zip").join(","),
    isDescriptor: name => /\.dsc$/i.test(name),
    isArchive: name => archivePattern.test(name),
    isDfsImage: name => dfsPattern.test(name) || archivePattern.test(name),
    isImage: name => imagePattern.test(name),
    isImportableImage: name => imagePattern.test(name) || archivePattern.test(name),
    isPotentialAdfsImage: name => adfsPattern.test(name),
    isRomImage: name => /\.rom[0-7]?$/i.test(name),
    stem: name => String(name).replace(/\.[^.]+$/, "")
  };
})();
