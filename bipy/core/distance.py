#!/usr/bin/env python
"""Core distance matrix API."""
from __future__ import division

#-----------------------------------------------------------------------------
# Copyright (c) 2013, The BiPy Developers.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from copy import deepcopy
from itertools import izip

import numpy as np
from scipy.spatial.distance import is_valid_dm, squareform


def random_distance_matrix(num_samples, sample_ids=None):
    """Return a ``DistanceMatrix`` populated with random distances.

    Distances are randomly drawn from a uniform distribution over ``[0, 1)``
    (see ``numpy.random.rand`` for more details). The distance matrix is
    guaranteed to be symmetric and hollow.

    Arguments:
    num_samples -- the number of samples in the resulting ``DistanceMatrix``.
        For example, if ``num_samples`` is 3, a 3x3 ``DistanceMatrix`` will be
        returned
    sample_ids -- a sequence of strings to be used as sample IDs.
        ``len(sample_ids)`` must be equal to ``num_samples``. If not provided,
        sample IDs will be monotonically-increasing integers cast as strings
        (numbering starts at 1). For example, ``('1', '2', '3')``

    """
    data = np.tril(np.random.rand(num_samples, num_samples), -1)
    data += data.T

    if not sample_ids:
        sample_ids = map(str, range(1, num_samples + 1))

    return DistanceMatrix(data, sample_ids)


class DistanceMatrixError(Exception):
    """General error for distance matrix validation failures."""
    pass


class MissingSampleIDError(Exception):
    """Error for sample ID lookup that doesn't exist in the distance matrix."""
    pass


class DistanceMatrixFormatError(Exception):
    """Error for reporting issues in distance matrix file format.

    Typically used during parsing.

    """
    pass


class SampleIDMismatchError(Exception):
    """Error for reporting a mismatch between sample IDs.

    Typically used during parsing.

    """

    def __init__(self):
        super(SampleIDMismatchError, self).__init__()
        self.args = ("Encountered mismatched sample IDs while parsing the "
                     "distance matrix file. Please ensure that the sample IDs "
                     "match between the distance matrix header (first row) "
                     "and the row labels (first column).",)


class MissingHeaderError(Exception):
    """Error for reporting a missing sample ID header line during parsing."""

    def __init__(self):
        super(MissingHeaderError, self).__init__()
        self.args = ("Could not find a header line containing sample IDs in "
                     "the distance matrix file. Please verify that the file "
                     "is not empty.",)


class MissingDataError(Exception):
    """Error for reporting missing data lines during parsing."""

    def __init__(self, actual, expected):
        super(MissingDataError, self).__init__()
        self.args = ("Expected %d row(s) of data, but found %d." % (expected,
                                                                    actual),)


class DistanceMatrix(object):
    """Encapsulate a 2D array of distances (floats) and sample IDs (labels).

    A ``DistanceMatrix`` instance contains a square, symmetric, and hollow 2D
    numpy ``ndarray`` of distances (floats) between samples. A tuple of sample
    IDs (typically strings) accompanies the raw distance data. Methods are
    provided to load and save distance matrices, as well as perform common
    operations such as extracting distances based on sample ID.

    The ``ndarray`` of distances can be accessed via the ``data`` property. The
    tuple of sample IDs can be accessed via the ``sample_ids`` property.
    ``sample_ids`` is also writeable, though the new sample IDs must match the
    number of samples in ``data``.

    The distances are stored in redundant (square-form) format. To facilitate
    use with other scientific Python routines (e.g., scipy), the distances can
    be retrieved in condensed (vector-form) format using ``condensed_form``.
    For more details on redundant and condensed formats, see:
    http://docs.scipy.org/doc/scipy/reference/spatial.distance.html

    """

    @classmethod
    def from_file(cls, dm_f, delimiter='\t'):
        """Load distance matrix from delimited text file.

        Given an open file-like object ``dm_f``, a ``DistanceMatrix`` instance
        is returned based on the parsed file contents.

        The file must contain delimited text (controlled via ``delimiter``).
        The first line must contain all sample IDs, where each ID is separated
        by ``delimiter``. The subsequent lines must contain a sample ID
        followed by each distance (float) between the sample and all other
        samples.

        For example, a 2x2 distance matrix with samples ``'a'`` and ``'b'``
        would look like:

        <tab>a<tab>b
        a<tab>0.0<tab>1.0
        b<tab>1.0<tab>0.0

        where ``<tab>`` is the delimiter between elements.

        Whitespace-only lines can occur anywhere throughout the file and are
        ignored. Lines starting with # are treated as comments and ignored.
        These comments can only occur *before* the sample ID header.

        """
        # We aren't using np.loadtxt because it uses *way* too much memory
        # (e.g, a 2GB matrix eats up 10GB, which then isn't freed after parsing
        # has finished). See:
        # http://mail.scipy.org/pipermail/numpy-tickets/2012-August/006749.html

        # Strategy:
        #     - find the header
        #     - initialize an empty ndarray
        #     - for each row of data in the input file:
        #         - populate the corresponding row in the ndarray with floats
        sids = cls._parse_sample_ids(dm_f, delimiter)
        num_sids = len(sids)
        data = np.empty((num_sids, num_sids), dtype='float')

        curr_row_idx = 0
        for line in dm_f:
            line = line.strip()

            if not line:
                continue
            elif curr_row_idx >= num_sids:
                # We've hit a nonempty line after we already filled the data
                # matrix. Raise an error because we shouldn't ignore extra
                # data.
                raise DistanceMatrixFormatError(
                    "Encountered extra rows without corresponding sample IDs "
                    "in the header.")

            tokens = line.split(delimiter)

            # +1 because the first column contains the sample ID.
            if len(tokens) != num_sids + 1:
                raise DistanceMatrixFormatError(
                    "The number of values in row number %d is not equal to "
                    "the number of sample IDs in the header."
                    % (curr_row_idx + 1))

            if tokens[0] == sids[curr_row_idx]:
                data[curr_row_idx, :] = np.asarray(tokens[1:], dtype='float')
            else:
                raise SampleIDMismatchError

            curr_row_idx += 1

        if curr_row_idx != num_sids:
            raise MissingDataError(curr_row_idx, num_sids)

        return cls(data, sids)

    def __init__(self, data, sample_ids):
        """Construct a ``DistanceMatrix`` instance.

        Arguments:
        data -- a square, symmetric, and hollow 2D ``numpy.ndarray`` of
            distances (floats), or a structure that can be converted to a
            ``numpy.ndarray`` using ``numpy.asarray``. Data will be converted
            to a float ``dtype`` if necessary. A copy will *not* be made if
            already an ``ndarray`` with a float ``dtype``
        sample_ids -- a sequence of strings to be used as sample labels. Must
            match the number of rows/cols in ``data``

        """
        data = np.asarray(data, dtype='float')
        sample_ids = tuple(sample_ids)
        self._validate(data, sample_ids)

        self._data = data
        self._sample_ids = sample_ids
        self._sample_index = self._index_list(self._sample_ids)

    @property
    def data(self):
        """Return a ``numpy.ndarray`` of distances.

        A copy is *not* returned. This property is not writeable.

        """
        return self._data

    @property
    def sample_ids(self):
        """Return a tuple of sample IDs.

        This property is writeable, but the number of new sample IDs must match
        the number of samples in ``data``.

        """
        return self._sample_ids

    @sample_ids.setter
    def sample_ids(self, sample_ids_):
        sample_ids_ = tuple(sample_ids_)
        self._validate(self.data, sample_ids_)
        self._sample_ids = sample_ids_
        self._sample_index = self._index_list(self._sample_ids)

    @property
    def dtype(self):
        """Return the ``dtype`` of the underlying ``numpy.ndarray``."""
        return self.data.dtype

    @property
    def shape(self):
        """Return a two-element tuple containing the array dimensions.

        As the distance matrix is guaranteed to be square, both tuple entries
        will be equal.

        """
        return self.data.shape

    @property
    def num_samples(self):
        """Returns the number of samples (i.e. number of rows or columns)."""
        return len(self.sample_ids)

    @property
    def size(self):
        """Return the total number of elements in the distance matrix.

        Equivalent to ``self.shape[0] * self.shape[1]``.

        """
        return self.data.size

    @property
    def T(self):
        """Return the transpose of the distance matrix."""
        return self.transpose()

    def transpose(self):
        """Return the transpose of the distance matrix.

        This is a no-op as the matrix is guaranteed to be symmetric.

        """
        return self

    def condensed_form(self):
        """Return a 1D ``numpy.ndarray`` vector of distances.

        The conversion is not a constant-time operation, though it should be
        relatively quick to perform.

        For more details on redundant and condensed formats, see:
        http://docs.scipy.org/doc/scipy/reference/spatial.distance.html

        """
        return squareform(self.data, force='tovector')

    def redundant_form(self):
        """Return a 2D ``numpy.ndarray`` of distances.

        As this is the native format that the distances are stored in, this is
        simply an alias for ``self.data``.

        Does *not* return a copy of the data.

        For more details on redundant and condensed formats, see:
        http://docs.scipy.org/doc/scipy/reference/spatial.distance.html

        """
        return self.data

    def copy(self):
        """Return a deep copy of the distance matrix."""
        # We deepcopy sample IDs in case the tuple contains mutable objects at
        # some point in the future.
        return self.__class__(self.data.copy(), deepcopy(self.sample_ids))

    def __str__(self):
        """Return a string representation of the distance matrix.

        Summary includes matrix dimensions, a (truncated) list of sample IDs,
        and (truncated) array of distances.

        """
        return '%dx%d distance matrix\nSample IDs:\n%s\nData:\n' % (
            self.shape[0], self.shape[1],
            self._pprint_sample_ids()) + str(self.data)

    def __eq__(self, other):
        """Return ``True`` if this distance matrix is equal to the other.

        Two distance matrices are equal if they have the same shape, sample IDs
        (in the same order!), and have data arrays that are equal.

        Checks are *not* performed to ensure that ``other`` is a
        ``DistanceMatrix`` instance.

        """
        equal = True

        # The order these checks are performed in is important to be as
        # efficient as possible. The check for shape equality is not strictly
        # necessary as it should be taken care of in np.array_equal, but I'd
        # rather explicitly bail before comparing IDs or data. Use array_equal
        # instead of (a == b).all() because of this issue:
        #     http://stackoverflow.com/a/10582030
        try:
            if self.shape != other.shape:
                equal = False
            elif self.sample_ids != other.sample_ids:
                equal = False
            elif not np.array_equal(self.data, other.data):
                equal = False
        except AttributeError:
            equal = False

        return equal

    def __ne__(self, other):
        """Return ``True`` if this distance matrix and the other are not equal.

        See ``__eq__`` for more details.

        """
        return not self == other

    def __getslice__(self, start, stop):
        """Support deprecated slicing method.

        Taken from http://stackoverflow.com/a/14555197 (including docstring):

        This solves a subtle bug, where __getitem__ is not called, and all the
        dimensional checking not done, when a slice of only the first dimension
        is taken, e.g. a[1:3]. From the Python docs:
           Deprecated since version 2.0: Support slice objects as parameters to
           the __getitem__() method. (However, built-in types in CPython
           currently still implement __getslice__(). Therefore, you have to
           override it in derived classes when implementing slicing.)
        """
        return self.__getitem__(slice(start, stop))

    def __getitem__(self, index):
        """Slice into the data by sample ID or numpy indexing.

        If ``index`` is a string, it is assumed to be a sample ID and a
        ``numpy.ndarray`` row vector is returned for the corresponding sample.
        The lookup based on sample ID is quick. ``MissingSampleIDError`` is
        raised if the sample does not exist.

        Otherwise, ``index`` will be passed through to
        ``DistanceMatrix.data.__getitem__``, allowing for standard indexing of
        a numpy ``ndarray`` (e.g., slicing).

        Arguments:
        index -- the sample ID whose row of distances will be returned, or the
            index to be passed through to the underlying data matrix

        """
        if isinstance(index, basestring):
            if index in self._sample_index:
                return self.data[self._sample_index[index]]
            else:
                raise MissingSampleIDError("The sample ID '%s' is not in the "
                                           "distance matrix." % index)
        else:
            return self.data.__getitem__(index)

    def to_file(self, out_f, delimiter='\t'):
        """Save the distance matrix to file in delimited text format.

        See ``from_file`` for more details on the file format.

        Arguments:
        out_f -- file-like object to write to
        delimiter -- delimiter used to separate elements in output format

        """
        formatted_sids = self._format_sample_ids(delimiter)
        out_f.write(formatted_sids)
        out_f.write('\n')

        for sid, vals in izip(self.sample_ids, self.data):
            out_f.write(sid)
            out_f.write(delimiter)
            out_f.write(delimiter.join(np.asarray(vals, dtype=np.str)))
            out_f.write('\n')

    @staticmethod
    def _parse_sample_ids(dm_f, delimiter):
        header_line = None

        for line in dm_f:
            line = line.strip()

            if line and not line.startswith('#'):
                header_line = line
                break

        if header_line is None:
            raise MissingHeaderError
        else:
            return header_line.split(delimiter)

    def _validate(self, data, sample_ids):
        # Accepts arguments instead of inspecting instance attributes because
        # we don't want to create an invalid distance matrix before raising an
        # error (because then it could be used after the exception is caught).
        num_sids = len(sample_ids)

        if 0 in data.shape:
            raise DistanceMatrixError("Data must be at least 1x1 in size.")
        elif num_sids != len(set(sample_ids)):
            raise DistanceMatrixError("Sample IDs must be unique.")
        elif not is_valid_dm(data):
            raise DistanceMatrixError("Data must be an array that is "
                                      "2-dimensional, square, symmetric, "
                                      "hollow, and contains only floating "
                                      "point values.")
        elif num_sids != data.shape[0]:
            raise DistanceMatrixError("The number of sample IDs must match "
                                      "the number of rows/columns in the "
                                      "data.")

    def _index_list(self, list_):
        return {id_: idx for idx, id_ in enumerate(list_)}

    def _format_sample_ids(self, delimiter):
        return delimiter.join([''] + list(self.sample_ids))

    def _pprint_sample_ids(self, max_chars=80, delimiter=', ', suffix='...',):
        """Adapted from http://stackoverflow.com/a/250373"""
        sids_str = delimiter.join(self.sample_ids)

        if len(sids_str) > max_chars:
            truncated = sids_str[:max_chars + 1].split(delimiter)[0:-1]
            sids_str = delimiter.join(truncated) + delimiter + suffix

        return sids_str